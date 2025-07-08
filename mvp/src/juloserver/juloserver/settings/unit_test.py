from .local_loadpost import *
import logging

logging.disable(logging.CRITICAL)
DEBUG = False
TEMPLATE_DEBUG = False
CELERY_ALWAYS_EAGER = True

CACHEOPS_ENABLED = False

DATABASES = {
    'default': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_OPS_NAME'),
        'USER': os.getenv('POSTGRESQL_OPS_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_OPS_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_OPS_HOST'),
        'PORT': os.getenv('POSTGRESQL_OPS_PORT'),
    },
    'replica': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_REPLICA_OPS_NAME'),
        'USER': os.getenv('POSTGRESQL_REPLICA_OPS_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_REPLICA_OPS_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_REPLICA_OPS_HOST'),
        'PORT': os.getenv('POSTGRESQL_REPLICA_OPS_PORT'),
    },
    'logging_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_LOGGING_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_LOGGING_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_LOGGING_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_LOGGING_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_LOGGING_DB_PORT'),
    },
    'julorepayment_async_replica': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_REPAYMENT_ASYNC_REPLICA_OPS_NAME'),
        'USER': os.getenv('POSTGRESQL_REPAYMENT_ASYNC_REPLICA_OPS_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_REPAYMENT_ASYNC_REPLICA_OPS_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_REPAYMENT_ASYNC_REPLICA_OPS_HOST'),
        'PORT': os.getenv('POSTGRESQL_REPAYMENT_ASYNC_REPLICA_OPS_PORT'),
    },
    'julo_analytics_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_ANA_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_ANA_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_ANA_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_ANA_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_ANA_DB_PORT'),
    },
    'bureau_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_BUREAU_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_BUREAU_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_BUREAU_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_BUREAU_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_BUREAU_DB_PORT'),
    },
    'onboarding_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_ONBOARDING_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_ONBOARDING_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_ONBOARDING_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_ONBOARDING_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_ONBOARDING_DB_PORT'),
    },
    'loan_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_LOAN_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_LOAN_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_LOAN_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_LOAN_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_LOAN_DB_PORT'),
    },
    'utilization_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_UTILIZATION_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_UTILIZATION_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_UTILIZATION_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_UTILIZATION_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_UTILIZATION_DB_PORT'),
    },
    'juloplatform_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_PLATFORM_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_PLATFORM_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_PLATFORM_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_PLATFORM_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_PLATFORM_DB_PORT'),
    },
    'partnership_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_DB_PORT'),
    },
    'partnership_onboarding_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_ONBOARDING_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_ONBOARDING_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_DB_PORT'),
    },
    'repayment_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_REPAYMENT_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_REPAYMENT_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_REPAYMENT_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_REPAYMENT_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_REPAYMENT_DB_PORT'),
    },
    'collection_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_COLLECTION_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_COLLECTION_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_COLLECTION_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_COLLECTION_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_COLLECTION_DB_PORT'),
    },
    'partnership_grab_db': {
        'ENGINE': 'juloserver.julocore.customized_psycopg2',
        'NAME': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_GRAB_DB_NAME'),
        'USER': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_GRAB_DB_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_GRAB_DB_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_GRAB_DB_HOST'),
        'PORT': os.getenv('POSTGRESQL_JULO_PARTNERSHIP_GRAB_DB_PORT'),
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    },
    "redis": {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    },
    'token': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    },
    'loc_mem': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

MIDDLEWARE_CLASSES = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'juloserver.standardized_api_response.api_middleware.StandardizedTestApiURLMiddleware',
    'juloserver.julocore.restapi.middleware.ApiLoggingMiddleware',
    'cuser.middleware.CuserMiddleware',
]

# agent Assignment Default agent
DEFAULT_USER_ID = 2041
TIME_SLEEP = 0
TIME_SLEEP_PAYMENT = 0
DELAY_FOR_REALTIME_EVENTS = 0
DELAY_FOR_MOENGAGE_API_CALL = 0
SUSPEND_SIGNALS = True
SUSPEND_SIGNALS_FOR_MOENGAGE = True


from django.test import TransactionTestCase
TransactionTestCase.multi_db = True

from mock import patch
import django
django.setup()

patcher = patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
mocking_post_event = patcher.start()

patcher_graduation_redis = patch('juloserver.graduation.services.get_redis_client')
mock_redis_graduation = patcher_graduation_redis.start()

patcher_cycle_day_redis = patch('juloserver.julo.context_managers.get_redis_client')
mock_cycle_day_redis = patcher_cycle_day_redis.start()


from collections import namedtuple
event_response = namedtuple('Response', ['status_code'])
mocking_post_event.return_value = event_response(status_code=200)

from juloserver.julo.services2.redis_helper import MockRedisHelper
mock_redis_graduation.return_value = MockRedisHelper()
mock_cycle_day_redis.return_value = MockRedisHelper()
