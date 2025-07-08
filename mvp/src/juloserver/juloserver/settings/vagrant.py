from .base import *  # noqa for flake8
from .base_celery import *  # noqa for flake8

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.9/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': os.getenv('POSTGRESQL_NAME'),
        'USER': os.getenv('POSTGRESQL_USER'),
        'PASSWORD': os.getenv('POSTGRESQL_PASSWORD'),
        'HOST': os.getenv('POSTGRESQL_HOST'),
        'PORT': os.getenv('POSTGRESQL_PORT'),
    }
}

LOGGING['handlers']['logfile_server']['level'] = 'DEBUG'
LOGGING['loggers']['juloserver']['level'] = 'DEBUG'

INSTALLED_APPS += (
    'debug_toolbar',
    'raven.contrib.django.raven_compat',
)

GCM_SERVER_KEY = os.getenv('GCM_SERVER_KEY')

CELERYBEAT_SCHEDULE['update-payment-status-every-night']['schedule'] = crontab(minute="*/1")
