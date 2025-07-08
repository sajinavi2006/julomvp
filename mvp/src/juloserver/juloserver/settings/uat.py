# Should be almost the same as production
from .base import *  # noqa for flake8
from .base_celery import *  # noqa for flake8

ENVIRONMENT = 'uat'
PROJECT_URL = "https://api-%s.julofinance.com" % ENVIRONMENT
LANDING_PAGE_URL = 'https://julo.co.id/'

SECURE_SSL_REDIRECT = False

INSTALLED_APPS += (
    'debug_toolbar',
    'raven.contrib.django.raven_compat',
)

RAVEN_CONFIG['environment'] = ENVIRONMENT

# Tasks not to be run for non-prod environments
turned_off_tasks = [
    'trigger_sms_payment',
    'send_email_payment_reminder',
    'scheduled_send_courtesy_call_data',
    'scheduled_send_t_minus_one_data',
    'send_voice_payment_reminder',
    'retry_send_voice_payment_reminder1',
    'retry_send_voice_payment_reminder2',
    'send_voice_account_payment_reminder',
    'retry_send_voice_account_payment_reminder1',
    'retry_send_voice_account_payment_reminder2',
    'send_voice_ptp_payment_reminder',
    'run_rudolf_friska_experiment',
    'run_cashback_reminder_experiment',
    'run_march_lottery_experiment',
    'run_april_rudolf_friska_experiment',
    'run_send_warning_letter1',
    'run_send_warning_letter2',
    'run_send_warning_letter3',
    'send_all_whatsapp_on_bukalapak',
    'juloserver.julo.tasks.run_send_warning_letters',
    # 'upload_julo_t0_data_to_centerix',
    # 'upload_julo_tminus1_data_to_centerix',
    # 'upload_julo_tplus1_to_4_data_centerix',
    # 'upload_julo_tplus5_to_10_data_centerix',
    'notify_eligible_customers_for_loan_refinancing',
    'get_token_authentication_from_cootek',
    'upload_FDC_data_to_SFTP',
    'download_result_FDC_from_SFTP',
    'send_automated_comms',
    'get_tasks_from_db_and_schedule_cootek',
    'upload_julo_t0_cootek_data_to_centerix',
    'run_fdc_api_resume',
    'run_fdc_for_failure_status',
    'run_fdc_api',
    'send_ramadan_email_campaign',
    'send_ramadan_pn_campaign',
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
    'upload_julo_t0_cootek_data_to_intelix',
    'trigger_download_outdated_loans_from_fdc',
    'trigger_download_statistic_from_fdc',
    'trigger_download_result_fdc',
    'trigger_upload_loans_data_to_fdc',
    'trigger_update_moengage_for_scheduled_events',
    'trigger_bulk_update_moengage_for_scheduled_loan_status_change_210',
    'trigger_to_update_due_date',
    'trigger_update_moengage_for_scheduled_application_status_change_events',
    'send_all_whatsapp_payment_reminders',
    'send_sms_lebaran_promo',
    'send_asian_games_campaign',
    'send_lebaran_campaign_2020_sms',
    'send_lebaran_campaign_2020_pn',
    'send_lebaran_campaign_2020_email',
    'send_all_proactive_refinancing_sms_reminder_10am',
    'trigger_alert_unexpected_fdc_status',
    'juloserver.payment_point.tasks.notification_related.send_slack_notification_sepulsa_remaining_balance',
    'juloserver.payment_point.tasks.notification_related.send_slack_notification_sepulsa_balance_reach_minimum_threshold',
    'send_email_sms_for_unsent_moengage',
    'juloserver.minisquad.tasks2.notifications.send_slack_notification_intelix_blacklist',
    'upload_axiata_disbursement_and_repayment_data_to_oss',
    'juloserver.collection_hi_season.tasks.trigger_run_collection_hi_season_campaign',
    'update_installation_data',
    'update_uninstallation_data',
    'send_voice_payment_reminder_grab',
    'retry_send_voice_payment_reminder_grab1',
    'retry_send_voice_payment_reminder_grab2',
    'revive_mtl_to_j1',
    'run_task_dynamic_entry_level',
    'run_retroload_bpjs_no_fdc_entry_level',
    'verify_ayoconnect_loan_disbursement_status',
    'check_payment_gateway_vendor_balance',
    'delete_old_customers',
    'revive_shopee_whitelist_el',
    'retry_anti_fraud_binary_checks',
    'hit_fdc_for_rejected_customers',
]
for task in turned_off_tasks:
    if task in CELERYBEAT_SCHEDULE:
        del CELERYBEAT_SCHEDULE[task]

DOKU_ACCOUNT_ID = 1075574584
SLACK_MONITORING_CHANNEL = "#mon_julodb_%s" % ENVIRONMENT
PRIMO_LIST_ID = 1000

FASPAY_PREFIX_MANDIRI = '88308220'
FASPAY_PREFIX_OLD_ALFAMART = '319322'
FASPAY_PREFIX_ALFAMART = '319320'
FASPAY_PREFIX_PERMATA = '851598'
FASPAY_PREFIX_OLD_PERMATA = '877332'
FASPAY_PREFIX_BRI = '234540'
FASPAY_PREFIX_MAYBANK = '78218220'
PREFIX_OLD_BCA = '188880'
PREFIX_BCA = '10994'
FASPAY_PREFIX_OLD_INDOMARET = '319327'
FASPAY_PREFIX_INDOMARET = '319321'
FASPAY_PREFIX_BNI = '9881236315'
FASPAY_PREFIX_BNI_V2 = '9881859305'
PREFIX_CIMB_NIAGA = '2051'
PREFIX_ONEKLIK_BCA = '820'
FASPAY_USER_ID = os.getenv('FASPAY_USER_ID')
FASPAY_PASSWORD = os.getenv('FASPAY_PASSWORD')

AGREEMENT_WEBSITE_2 = "https://julo.co.id/surat2/staging/{customer_id}/"
AGREEMENT_WEBSITE_3 = "https://julo.co.id/surat3/staging/{customer_id}/"
AGREEMENT_WEBSITE = "https://julo.co.id/surat/staging/{customer_id}/"

# gopay
GOPAY_SNAP_BASE_URL = "https://app.sandbox.midtrans.com"
GOPAY_BASE_URL = "https://api.sandbox.midtrans.com"
PAYMENT_DETAILS = "https://cms-uat.julo.co.id/payment_detail/"
WARNING_LETTER = "https://web-dev.julo.co.id/warning_letter/staging/"
JULO_WEB_URL = "https://app-uat.julo.co.id"

#BNI VA generation email notification reminder email_to and email_cc
BNI_VA_EMAIL_TO = ['raymond.wijaya@julofinance.com', 'jane.michaela@julofinance.com']
BNI_VA_EMAIL_CC = 'kiran.a@julofinance.com'

MAGIC_LINK_BASE_URL = "https://web-dev.julo.co.id/magic_link/uat/"
# Newsletter
CMS_FILES_NEWLATTER = "https://cms-uat.julo.co.id/sites/default/files/newsletter/"

# agent Assignment Default agent
DEFAULT_USER_ID = 1488

# JULO RECOGNITION
REKOGNITION_DEFAULT_COLLECTION = "julo_rekognition_dev"


# MINTOS
MINTOS_REQUEST_LIMIT = 160

# Intelix
INTELIX_BASE_URL = "https://rnd.ecentrix.net/ecx_ws/"
# Koleko
KOLEKO_DIRECTORY_PATH = "uat/"

# Sepulsa
NEW_SEPULSA_BASE_URL = "https://horven-api.sumpahpalapa.com/api/"

MISSION_WEB_URL = "https://cms-uat.julo.co.id"
EASY_INCOME_AUTH_SECRET_KEY = os.getenv("EASY_INCOME_AUTH_SECRET_KEY")
DEFAULT_TOKEN_EXPIRE_AFTER_HOURS = "24"

AUTODEBET_MANDIRI_BASE_URL = 'https://dev.yokke.bankmandiri.co.id'

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
