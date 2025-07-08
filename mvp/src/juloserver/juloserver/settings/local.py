# Quick-start development settings - unsuitable for production
from .base import *  # noqa for flake8
from .base_celery import *  # noqa for flake8
import os

ENVIRONMENT = 'dev'

PROJECT_URL = os.getenv("PROJECT_URL", "http://localhost:8000")
LANDING_PAGE_URL = 'https://julo.co.id/'

MEDIA_URL = '/home/herman/App/git/jc-h-document-upload/src/juloserver/media/'
# ALLOWED_HOSTS = ['http://localhost:8000']

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DJANGO_DEBUG", "true") == "true"
ALLOWED_HOSTS = [os.getenv("ALLOWED_HOSTS", "localhost")]
SECURE_SSL_REDIRECT = False
CSRF_COOKIE_SECURE = False

LOGGING['handlers']['logfile_server']['level'] = 'DEBUG'
LOGGING['loggers']['juloserver']['level'] = 'DEBUG'

INSTALLED_APPS += ('debug_toolbar',)


CELERYBEAT_SCHEDULE['update-payment-status-every-night']['schedule'] = crontab(minute="*/30")
CELERYBEAT_SCHEDULE['mark-offer-expired-every-night']['schedule'] = crontab(minute="*/30")
CELERYBEAT_SCHEDULE['mark-sphp-expired-every-night']['schedule'] = crontab(minute="*/30")
CELERYBEAT_SCHEDULE['mark-sphp-expired-every-night-julo-one']['schedule'] = crontab(minute="*/30")

REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES']= (
    'rest_framework.renderers.JSONRenderer',
    'rest_framework.renderers.BrowsableAPIRenderer',
)

# Tasks not to be run for non-prod environments
turned_off_tasks = [
    'trigger_sms_payment',
    'send_email_payment_reminder',
    'scheduled_send_courtesy_call_data',
    'scheduled_send_t_minus_one_data',
    'run_lebaran_campaign_2020_sms_1',
    'run_lebaran_campaign_2020_sms_2',
    'sms_campaign_for_non_contacted_customer_7am_apr20',
    'sms_campaign_for_non_contacted_customer_7am_may11',
    'sms_campaign_for_non_contacted_customer_12h30pm_apr27',
    'sms_campaign_for_non_contacted_customer_12h30pm_may18',
    'sms_campaign_for_non_contacted_customer_5pm_may4',
    'sms_campaign_for_non_contacted_customer_5pm_may25',
    'run_send_sms_repayment_awareness_campaign',
    'send_ramadhan_sms_campaign',
    'send_all_sms_payment_reminders',
    'run_send_sms_osp_recovery_7am',
    'run_send_sms_osp_recovery_11am',
    'send_sms_reminder_138',
    'send_sms_reminder_175_daily_8am',
    'send_all_sms_on_bukalapak',
    'send_automated_comms',
    'trigger_scheduled_moengage_bulk_upload',
    'run_march_lottery_experiment',
    'run_rudolf_friska_experiment',
    'run_april_rudolf_friska_experiment',
    'send_all_whatsapp_payment_reminders',
    'send_sms_lebaran_promo',
    'send_asian_games_campaign',
    'send_lebaran_campaign_2020_sms',
    'send_lebaran_campaign_2020_pn',
    'send_lebaran_campaign_2020_email',
    'send_all_proactive_refinancing_sms_reminder_10am',
    'trigger_alert_unexpected_fdc_status',
    'send_voice_payment_reminder_grab',
    'retry_send_voice_payment_reminder_grab1',
    'retry_send_voice_payment_reminder_grab2',
    'verify_ayoconnect_loan_disbursement_status',
    'check_payment_gateway_vendor_balance'
]
for task in turned_off_tasks:
    if task in CELERYBEAT_SCHEDULE:
        del CELERYBEAT_SCHEDULE[task]

DOKU_ACCOUNT_ID = 1345280817
PRIMO_LIST_ID = 1000

FASPAY_PREFIX_OLD_ALFAMART = '319322'
FASPAY_PREFIX_ALFAMART = '319320'
PREFIX_OLD_BCA = '188880'
PREFIX_BCA = '10994'
FASPAY_PREFIX_BRI = '234540'
FASPAY_PREFIX_OLD_INDOMARET = '319327'
FASPAY_PREFIX_INDOMARET = '319321'
FASPAY_PREFIX_MANDIRI = '88308220'
FASPAY_PREFIX_PERMATA = '851598'
FASPAY_PREFIX_OLD_PERMATA = '877332'
FASPAY_PREFIX_MAYBANK = '78218220'
FASPAY_PREFIX_BNI = '9881236315'
FASPAY_PREFIX_BNI_V2 = '9881859305'
PREFIX_CIMB_NIAGA = '2051'
PREFIX_ONEKLIK_BCA = '820'

AGREEMENT_WEBSITE = "https://julo.co.id/surat/dev/{customer_id}/"
try:
    from .local_personal import *
except ImportError:
    pass

AGREEMENT_WEBSITE_2 = "https://julo.co.id/surat2/dev/{customer_id}/"
AGREEMENT_WEBSITE_3 = "https://julo.co.id/surat3/dev/{customer_id}/"

PAYMENT_DETAILS = "https://julo.co.id/payment_detail/dev/"
WARNING_LETTER = "https://web-dev.julo.co.id/warning_letter/dev/"
MAGIC_LINK_BASE_URL = "https://web-dev.julo.co.id/magic_link/local/"

#Newsletter 
CMS_FILES_NEWLATTER = "https://julo.co.id/sites/default/files/newsletter/"

DEFAULT_USER_ID = 1

# JULO RECOGNITION
REKOGNITION_DEFAULT_COLLECTION = "julo_rekognition_test"

# MINTOS
MINTOS_REQUEST_LIMIT = 160

# Intelix
INTELIX_BASE_URL = "https://rnd.ecentrix.net/ecx_ws/"

# Sepulsa
NEW_SEPULSA_BASE_URL = "https://horven-api.sumpahpalapa.com/api/"

# MO-ENGAGE
SUSPEND_SIGNALS = True
SUSPEND_SIGNALS_FOR_MOENGAGE = True

# Koleko
KOLEKO_DIRECTORY_PATH = "dev/"

# Xendit - Autodebit BRI
XENDIT_AUTODEBET_BASE_URL = "https://api.xendit.co"
XENDIT_AUTODEBET_API_KEY = "xnd_development_oLw9L79NXJiXMprNKxeszALH2UozW6KU8Pnh6YfIBhzazSzhgcxXxXOh7iofH"
XENDIT_AUTODEBET_CALLBACK_TOKEN = "seJMHtEj899zq4udATMtb9M0uY6rW22dtAtU2vv2eYdNZop0"

# Gopay
GOPAY_SERVER_KEY = "SB-Mid-server-9h05ZDCZS8oen3GHYn0C9Uic"

#BNI VA generation email notification reminder email_to and email_cc
BNI_VA_EMAIL_TO = ['raymond.wijaya@julofinance.com', 'jane.michaela@julofinance.com']
BNI_VA_EMAIL_CC = 'kiran.a@julofinance.com'

TEMPLATES = [
    {
        'APP_DIRS': True,
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'juloserver', 'templates/html'),
            os.path.join(BASE_DIR, 'juloserver', 'templates/txt')
        ],
        'OPTIONS': {
            'context_processors': [
                # Custom Context Processor(s)
                'core.context_processors.julo',

                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                'django.template.context_processors.media',
                'django.template.context_processors.csrf',
                'django.template.context_processors.tz',
                'django.template.context_processors.static'
            ],
            # 'loaders': [
            #     ('django.template.loaders.cached.Loader', [
            #         'django.template.loaders.filesystem.Loader',
            #         'django.template.loaders.app_directories.Loader',
            #     ]),
            # ],
            'debug': True,
        },
    },
]

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
FASPAY_SNAP_OUTBOUND_MERCHANT_ID_ALAFMART = '31932'
FASPAY_SNAP_OUTBOUND_MERCHANT_ID_INDOMARET = '31932'
FASPAY_SNAP_OUTBOUND_MERCHANT_ID_PERMATA = '31932'
