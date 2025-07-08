# Should be almost the same as staging
from .base import *  # noqa for flake8
from .base_celery import *  # noqa for flake8
from ddtrace import config, patch, tracer # for datadog agent
import os
import socket

ENVIRONMENT = 'prod'
PROJECT_URL = "https://api.julofinance.com"
LANDING_PAGE_URL = 'https://julo.co.id/'

SECURE_SSL_REDIRECT = False

INSTALLED_APPS += (
    'raven.contrib.django.raven_compat',
)

RAVEN_CONFIG['environment'] = ENVIRONMENT
RAVEN_CONFIG['release'] = os.getenv('RELEASE_VERSION')

EMAIL_HOST_USER = "no-reply@julofinance.com"
EMAIL_HOST_PASSWORD = "88Julo88"
DOKU_ACCOUNT_ID = 1262040917  # TODO: move to ansible env vars
SLACK_MONITORING_CHANNEL = "#mon_julodb_%s" % ENVIRONMENT
PRIMO_LIST_ID = 1001

FASPAY_PREFIX_MANDIRI = '88308220'
FASPAY_PREFIX_OLD_ALFAMART = '319322'
FASPAY_PREFIX_ALFAMART = '319320'
FASPAY_PREFIX_OLD_PERMATA = '877332'
FASPAY_PREFIX_PERMATA = '851598'
FASPAY_PREFIX_BRI = '234540'
FASPAY_PREFIX_MAYBANK = '78218220'
PREFIX_OLD_BCA = '188880'
PREFIX_BCA = '10994'
FASPAY_PREFIX_OLD_INDOMARET = '319327'
FASPAY_PREFIX_INDOMARET = '319321'
FASPAY_PREFIX_BNI = '9881859302'
FASPAY_PREFIX_BNI_V2 = '9881859305'
PREFIX_CIMB_NIAGA = '2051'
PREFIX_ONEKLIK_BCA = '820'

DATADOG_TRACE['TAGS']['env'] = ENVIRONMENT

if 'http' not in STATIC_URL:
    STATIC_URL = BASE_URL + '/static/'

AGREEMENT_WEBSITE_2 = "https://julo.co.id/surat2/{customer_id}/"
AGREEMENT_WEBSITE_3 = "https://julo.co.id/surat3/{customer_id}/"
AGREEMENT_WEBSITE = "https://julo.co.id/surat/{customer_id}/"

# gopay
GOPAY_SNAP_BASE_URL = "https://app.midtrans.com"
GOPAY_BASE_URL = "https://api.midtrans.com"
PAYMENT_DETAILS = "https://julo.co.id/payment_detail/"
WARNING_LETTER = "https://julo.co.id/warning_letter/"
JULO_WEB_URL = "https://app.julo.co.id"

#BNI VA generation email notification reminder email_to and email_cc
BNI_VA_EMAIL_TO = ['chris.paulus@julofinance.com', 'tiarani.nurfadilla@julofinance.com', 'customercare@faspay.co.id']
BNI_VA_EMAIL_CC = ['partnership@faspay.co.id']

# Newsletter
CMS_FILES_NEWLATTER = "https://julo.co.id/sites/default/files/newsletter/"

MAGIC_LINK_BASE_URL = "https://julo.co.id/magic_link/"

# agent Assignment Default agent
DEFAULT_USER_ID = 1695

# JULO RECOGNITION
REKOGNITION_DEFAULT_COLLECTION = "julo_rekognition_prod"


# MINTOS
MINTOS_REQUEST_LIMIT = 500

# Intelix
INTELIX_BASE_URL = "https://julo2.ecentrix.net/ecx_ws/"

# Sepulsa
NEW_SEPULSA_BASE_URL = "https://kraken-api.sepulsa.id/api/"

# Koleko
KOLEKO_DIRECTORY_PATH = "prd/"

REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES']= (
    'rest_framework.renderers.JSONRenderer',
)

##DATADOG
DD_ENV = ENVIRONMENT
DD_TRACE_SAMPLING_RULES = [
    {
    "sample_rate": "0.0",
    "service": SERVICE_DOMAIN + "-defaultdb"
    },
]
#django
hostname = socket.gethostname()
if 'crm' in hostname:
    config.django["service_name"] = SERVICE_DOMAIN + '-crm'
else:
    config.django["service_name"] = SERVICE_DOMAIN + '-api'
config.django["cache_service_name"] = SERVICE_DOMAIN + '-cache'
config.django["database_service_name_prefix"] = SERVICE_DOMAIN + '-'
#celery
patch(celery=True)
patch(psycopg=True)
tracer.set_tags({
    'env': ENVIRONMENT,
    'host': hostname,
    'version': os.getenv('RELEASE_VERSION'),
    'domain' : SERVICE_DOMAIN
})
config.psycopg["service"] = SERVICE_DOMAIN + '-postgres'
config.celery['producer_service_name'] = SERVICE_DOMAIN + '-producer'
config.celery['worker_service_name'] = SERVICE_DOMAIN + '-async'

# For PDAM
PDAM_PRODUCTID = 291

MISSION_WEB_URL = "https://www.julo.co.id"
EASY_INCOME_AUTH_SECRET_KEY = os.getenv("EASY_INCOME_AUTH_SECRET_KEY")
DEFAULT_TOKEN_EXPIRE_AFTER_HOURS = "24"

AUTODEBET_MANDIRI_BASE_URL = 'https://api.yokke.bankmandiri.co.id'

# DOKU VIRTUAL ACCOUNT SNAP
PARTNER_SERVICE_ID_MANDIRI_DOKU = '89022'
PARTNER_SERVICE_ID_BRI_DOKU = '13924'
PARTNER_SERVICE_ID_PERMATA_DOKU = '8856'
PREFIX_MANDIRI_DOKU = '890229012'
PREFIX_BRI_DOKU = '139247003'
PREFIX_PERMATA_DOKU = '88565125'

# ONEKLIK BCA
ONEKLIK_BCA_CHANNEL_ID = "95221"
ONEKLIK_BCA_MERCHANT_ID = "61081"

# FASPAY SNAP OUTBOUND
FASPAY_SNAP_OUTBOUND_BASE_URL = os.getenv('FASPAY_SNAP_OUTBOUND_BASE_URL')
FASPAY_SNAP_OUTBOUND_CHANNEL_ID = '77001'
FASPAY_SNAP_OUTBOUND_PRIVATE_KEY = os.getenv('FASPAY_SNAP_OUTBOUND_PRIVATE_KEY')
FASPAY_SNAP_OUTBOUND_MERCHANT_ID = '31932'
FASPAY_SNAP_OUTBOUND_MERCHANT_ID_BNI_V2 = '36233'
FASPAY_SNAP_OUTBOUND_MERCHANT_ID_ALAFMART = '32401'
FASPAY_SNAP_OUTBOUND_MERCHANT_ID_INDOMARET = '32401'
FASPAY_SNAP_OUTBOUND_MERCHANT_ID_PERMATA = '32401'

# General Channeling
NOTIFY_WHEN_LOAN_CANCEL_SLACK_NOTIFICATION_CHANNEL = '#temp-loan-channeling'
