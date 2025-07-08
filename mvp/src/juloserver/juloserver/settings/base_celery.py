from __future__ import absolute_import
from kombu import Exchange
from kombu import Queue
# Register your new serializer methods into kombu
from kombu.serialization import register
from celery.schedules import crontab
import os

from .collection_celery import COLLECTION_CELERYBEAT_SCHEDULE
from .loan_refinancing_celery import LOAN_REFINANCING_CELERYBEAT_SCHEDULE
from .promo_campaign_celery import PROMO_CAMPAIGN_CELERYBEAT_SCHEDULE
from .moengage_upload_celery import MOENGAGE_UPLOAD_CELERYBEAT_SCHEDULE
from .fdc_celery import FDC_CELERYBEAT_SCHEDULE
from .pickle_custom import pickle_dumps, unpickle
from juloserver.customer_module.settings import (
    ACCOUNT_DELETION_CELERY_SCHEDULE,
    AUTO_APPROVAL_CONSENT_WITHDRAWAL_CELERY_SCHEDULE,
    CLEANUP_PAYDAY_CHANGE_REQUEST_FROM_REDIS_SCHEDULE,
    POPULATE_CUSTOMER_XID_CELERY_SCHEDULE,
    RETROFIX_DELETED_APPLICATION_186_SCHEDULE,
    RETROFIX_OLD_DELETION_DATA_SCHEDULE,
)
from juloserver.autodebet.settings import AUTODEBET_SCHEDULE
from juloserver.sales_ops.settings import SALES_OPS_SCHEDULE
from juloserver.julovers.settings import JULOVERS_SCHEDULE
from juloserver.channeling_loan.settings import CHANNELING_SCHEDULE
from juloserver.account.settings import ACCOUNT_SCHEDULE
from juloserver.account_payment.settings import ACCOUNT_PAYMENT_SCHEDULE
from juloserver.disbursement.settings import DISBURSEMENT_SCHEDULE
from juloserver.followthemoney.settings import FOLLOWTHEMONEY_SCHEDULE
from juloserver.payment_point.settings import PAYMENT_POINT_SCHEDULE
from juloserver.lenderinvestment.settings import LENDERINVESTMENT_SCHEDULE
from juloserver.collection_hi_season.settings import COLLECTION_HI_SEASON_CELERY_SCHEDULE
from juloserver.cashback.settings import CASHBACK_CELERY_SCHEDULE
from juloserver.graduation.settings import GRADUATION_SCHEDULE
from juloserver.dana.dana_celery import DANA_SCHEDULE
from juloserver.ovo.ovo_celery import OVO_SCHEDULE
from juloserver.julo_starter.julo_starter_celery import JULO_STARTER_SCHEDULE
from juloserver.fraud_security.settings import FRAUD_SECURITY_SCHEDULE
from juloserver.education.settings import EDUCATION_SCHEDULE
from juloserver.merchant_financing.merchant_financing_celery import MERCHANT_FINANCING_SCHEDULE
from juloserver.promo.settings import PROMO_CMS_SCHEDULE
from juloserver.julo.settings import IN_APP_ACCOUNT_DELETION_CELERY_SCHEDULE
from juloserver.dana_linking.settings import DANA_LINKING_SCHEDULE
from juloserver.partnership.settings import (
    PRODUCT_FINANCING_SCHEDULE,
    PARTNERSHIP_SCHEDULE,
    LEADGEN_WEBAPP_RESUME_APPLICATION_STUCK_105,
)
from juloserver.loan.settings import LOAN_SCHEDULE
from juloserver.loyalty.settings import LOYALTY_SCHEDULE
from juloserver.payback.settings import PAYBACK_SCHEDULE
from juloserver.oneklik_bca.settings import ONEKLIK_SCHEDULE
from juloserver.minisquad.settings import MINISQUAD_SCHEDULE
from juloserver.omnichannel.settings import OMNICHANNEL_SCHEDULE
from juloserver.balance_consolidation.settings import BALANCE_CONSOLIDATION_SCHEDULE
from juloserver.sales_ops_pds.settings import SALES_OPS_PDS_SCHEDULE
from juloserver.payment_gateway.constants import Vendor
from juloserver.referral.settings import REFERRAL_SCHEDULE

register(
    'pickle', pickle_dumps, unpickle,
    content_type='application/x-python-serialize',
    content_encoding='binary')

CELERY_QUEUES = (
    Queue('high', Exchange('high'), routing_key='high'),
    Queue('normal', Exchange('normal'), routing_key='normal'),
    Queue('low', Exchange('low'), routing_key='low'),
    Queue('lower', Exchange('lower'), routing_key='lower'),

    Queue('collection_high', Exchange('collection_high'), routing_key='collection_high'),
    Queue('collection_normal', Exchange('collection_normal'), routing_key='collection_normal'),
    Queue('collection_low', Exchange('collection_low'), routing_key='collection_low'),

    Queue('collection_dialer_low', Exchange('collection_dialer_low'),
          routing_key='collection_dialer_low'),
    Queue('collection_dialer_normal', Exchange('collection_dialer_normal'),
          routing_key='collection_dialer_normal'),
    Queue('collection_dialer_high', Exchange('collection_dialer_high'),
          routing_key='collection_dialer_high'),

    Queue('moengage_low', Exchange('moengage_low'), routing_key='moengage_low'),
    Queue('moengage_high', Exchange('moengage_high'), routing_key='moengage_high'),

    Queue('repayment_high', Exchange('repayment_high'), routing_key='repayment_high'),
    Queue('repayment_normal', Exchange('repayment_normal'), routing_key='repayment_normal'),
    Queue('repayment_low', Exchange('repayment_low'), routing_key='repayment_low'),
    Queue('fdc_inquiry', Exchange('fdc_inquiry'), routing_key='fdc_inquiry'),
    Queue('update_account_payment', Exchange('update_account_payment'),
          routing_key='update_account_payment'),
    Queue('bank_inquiry', Exchange('bank_inquiry'), routing_key='bank_inquiry'),

    Queue('loan_high', Exchange('loan_high'), routing_key='loan_high'),
    Queue(
        'channeling_loan_high', Exchange('channeling_loan_high'), routing_key='channeling_loan_high'
    ),
    Queue('loan_normal', Exchange('loan_normal'), routing_key='loan_normal'),
    Queue('loan_low', Exchange('loan_low'), routing_key='loan_low'),

    Queue('application_high', Exchange('application_high'), routing_key='application_high'),
    Queue('application_normal', Exchange('application_normal'), routing_key='application_normal'),
    Queue('application_low', Exchange('application_low'), routing_key='application_low'),
    Queue('application_pusdafil', Exchange('application_pusdafil'),
          routing_key='application_pusdafil'),
    Queue('application_xfers', Exchange('application_xfers'), routing_key='application_xfers'),
    Queue("application_xid", Exchange("application_xid"), routing_key="application_xid"),

    # PROJECT DRAGON BALL
    Queue('application_customer_sync', Exchange('application_customer_sync'), routing_key='application_customer_sync'),

    # GRAB QUEUE START
    Queue('grab_halt_queue', Exchange('grab_halt_queue'), routing_key='grab_halt_queue'),
    Queue('grab_resume_queue', Exchange('grab_resume_queue'), routing_key='grab_resume_queue'),
    Queue('grab_global_queue', Exchange('grab_global_queue'), routing_key='grab_global_queue'),
    Queue('grab_deduction_main_queue', Exchange('grab_deduction_main_queue'),
          routing_key='grab_deduction_main_queue'),
    Queue('grab_deduction_sub_queue', Exchange('grab_deduction_sub_queue'),
          routing_key='grab_deduction_sub_queue'),
    Queue('grab_collection_queue', Exchange('grab_collection_queue'),
          routing_key='grab_collection_queue'),
    Queue('grab_create_loan_details_queue', Exchange('grab_create_loan_details_queue'),
          routing_key='grab_create_loan_details_queue'),

    Queue('partner_mf_global_queue', Exchange('partner_mf_global_queue'),
          routing_key='partner_mf_global_queue'),
    Queue('partner_mf_cronjob_queue', Exchange('partner_mf_cronjob_queue'),
          routing_key='partner_mf_cronjob_queue'),
    Queue('partner_mf_merchant_historical_transaction_queue',
          Exchange('partner_mf_merchant_historical_transaction_queue'),
          routing_key='partner_mf_merchant_historical_transaction_queue'),
    Queue('automated_hiseason', Exchange('automated_hiseason'), routing_key='automated_hiseason'),

    Queue('partner_axiata_global_queue', Exchange('partner_axiata_global_queue'),
          routing_key='partner_axiata_global_queue'),
    Queue('partner_axiata_cronjob_queue', Exchange('partner_axiata_cronjob_queue'),
          routing_key='partner_axiata_cronjob_queue'),
    Queue('send_grab_api_timeout_alert_slack', Exchange('send_grab_api_timeout_alert_slack'),
          routing_key='send_grab_api_timeout_alert_slack'),
    Queue('comms', Exchange('comms'), routing_key='comms'),
    Queue('partnership_global', Exchange('partnership_global'), routing_key='partnership_global'),

    # EMPLOYEE FINANCING
    Queue('employee_financing_global_queue', Exchange('employee_financing_global_queue'),
          routing_key='employee_financing_global_queue'),
    Queue('employee_financing_email_at_190_queue',
          Exchange('employee_financing_email_at_190_queue'),
          routing_key='employee_financing_email_at_190_queue'),
    Queue('employee_financing_email_disbursement_queue',
          Exchange('employee_financing_email_disbursement_queue'),
          routing_key='employee_financing_email_disbursement_queue'),

    # Leadgen
    Queue('partner_leadgen_global_queue', Exchange('partner_leadgen_global_queue'),
          routing_key='partner_leadgen_global_queue'),

    # Paylater Whitelabel
    Queue('paylater_global_queue', Exchange('paylater_global_queue'),
          routing_key='paylater_global_queue'),

    # Dana
    Queue('dana_global_queue', Exchange('dana_global_queue'), routing_key='dana_global_queue'),
    Queue(
        'dana_transaction_queue',
        Exchange('dana_transaction_queue'),
        routing_key='dana_transaction_queue',
    ),
    Queue('dana_collection_queue', Exchange('dana_collection_queue'),
          routing_key='dana_collection_queue'),
    Queue(
        "dana_collection_data_preparation_queue",
        Exchange("dana_collection_data_preparation_queue"),
        routing_key="dana_collection_data_preparation_queue",
    ),
    Queue(
        "dana_lender_settlement_file_queue",
        Exchange("dana_lender_settlement_file_queue"),
        routing_key="dana_lender_settlement_file_queue",
    ),
    Queue('dana_collection_high_queue', Exchange('dana_collection_high_queue'),
          routing_key='dana_collection_high_queue'),
    Queue('dana_late_fee_queue', Exchange('dana_late_fee_queue'),
          routing_key='dana_late_fee_queue'),
    Queue('dana_callback_fdc_status_queue', Exchange('dana_callback_fdc_status_queue'),
          routing_key='dana_callback_fdc_status_queue'),
    Queue('dana_dialer_call_results_queue', Exchange('dana_dialer_call_results_queue'),
          routing_key='dana_dialer_call_results_queue'),
    Queue('dana_loan_agreement_queue', Exchange('dana_loan_agreement_queue'),
          routing_key='dana_loan_agreement_queue'),

    # SEON
    Queue('seon_global_queue', Exchange('seon_global_queue'), routing_key='seon_global_queue'),
    # Monnai
    Queue('monnai_global_queue', Exchange('monnai'), routing_key='monnai_global_queue'),
    # General Fraud related
    Queue('fraud', Exchange('fraud'), routing_key='fraud'),
    # Nexmo Robocall
    Queue('nexmo_robocall', Exchange('nexmo_robocall'), routing_key='nexmo_robocall'),
    # Pii Vault
    Queue(
        'antifraud_pii_vault', Exchange('antifraud_pii_vault'), routing_key='antifraud_pii_vault'
    ),
    # Dialer
    Queue('dialer_call_results_queue', Exchange('dialer_call_results_queue'), routing_key='dialer_call_results_queue'),

    # anti fraud
    Queue('face_matching', Exchange('face_matching'), routing_key='face_matching'),
    # User Action Log
    Queue('user_action_log', Exchange('user_action_log'), routing_key='user_action_log'),
    Queue(
        'repayment_pii_vault', Exchange('repayment_pii_vault'), routing_key='repayment_pii_vault'
    ),

    # Juicy Score
    Queue('juicy_score_queue', Exchange('juicy_score_queue'), routing_key='juicy_score_queue'),
    Queue(
        'loan_pii_vault', Exchange('loan_pii_vault'),
        routing_key='loan_pii_vault'
    ),
    Queue(
        'partnership_pii_vault',
        Exchange('partnership_pii_vault'),
        routing_key='partnership_pii_vault',
    ),
    Queue('platform_pii_vault', Exchange('platform_pii_vault'), routing_key='platform_pii_vault'),
    # Communication Squad
    Queue('outbound_call_core', Exchange('outbound_call_core'), routing_key='outbound_call_core'),
    Queue('outbound_call_dana', Exchange('outbound_call_dana'), routing_key='outbound_call_dana'),
    # SMS Campaign Dashboard
    Queue(
        'platform_campaign_sms_send',
        Exchange('platform_campaign_sms_send'),
        routing_key='platform_campaign_sms_send',
    ),
    # Streamlined Communication User segment
    Queue(
        'comms_user_segment_upload_queue',
        Exchange('comms_user_segment_upload_queue'),
        routing_key='comms_user_segment_upload_queue',
    ),
    Queue('autodebet_bca', Exchange('autodebet_bca'), routing_key='autodebet_bca'),
    Queue(
        'payment_gateway_transfer',
        Exchange('payment_gateway_transfer'),
        routing_key='payment_gateway_transfer',
    ),
    # Repopulate zipcode
    Queue(
        'repopulate_zipcode_queue',
        Exchange('repopulate_zipcode_queue'),
        routing_key='repopulate_zipcode_queue',
    ),
)

CELERY_DEFAULT_QUEUE = 'normal'
CELERY_DEFAULT_EXCHANGE = 'normal'
CELERY_DEFAULT_ROUTING_KEY = 'normal'

CELERY_TASK_PROTOCOL = 1
CELERY_TASK_SERIALIZER = "pickle"
CELERY_ACCEPT_CONTENT = ["pickle"]

MOENGAGE_IO_LOW_QUEUE = 'eventlet_collection_low'
MOENGAGE_IO_HIGH_QUEUE = 'eventlet_collection_high'

CELERYD_MAX_TASKS_PER_CHILD = 100

CELERY_SEND_TASK_SENT_EVENT = True

BROKER_TRANSPORT_OPTIONS = {
    'confirm_publish': os.getenv('CELERY_BROKER_CONFIRM_PUBLISH', False)
}

CELERY_ROUTES = {
    # 'send_email_payment_reminder': {'queue': 'low', 'routing_key': 'low'},
    # 'reminder_email_application_status_105_subtask': {'queue': 'low', 'routing_key': 'low'},
    'expire_application_status': {'queue': 'low', 'routing_key': 'low'},
    'update_late_fee_amount_task': {'queue': 'collection_low', 'routing_key': 'collection_low'},
    # 'send_submit_document_reminder_am_subtask': {'queue': 'low', 'routing_key': 'low'},
    'mark_sphp_expired_subtask': {'queue': 'low', 'routing_key': 'low'},
    # 'pn_app_105_subtask': {'queue': 'low', 'routing_key': 'low'},
    # 'send_voice_payment_reminder': {'queue': 'high', 'routing_key': 'high'},
    # 'retry_send_voice_payment_reminder1': {'queue': 'high', 'routing_key': 'high'},
    # 'retry_send_voice_payment_reminder2': {'queue': 'high', 'routing_key': 'high'},
    # 'send_voice_account_payment_reminder': {'queue': 'high', 'routing_key': 'high'},
    # 'retry_send_voice_account_payment_reminder1': {'queue': 'high', 'routing_key': 'high'},
    # 'retry_send_voice_account_payment_reminder2': {'queue': 'high', 'routing_key': 'high'},
    'run_wa_experiment': {'queue': 'high', 'routing_key': 'high'},
    'mark_form_partial_expired_subtask': {'queue': 'low', 'routing_key': 'low'},
    'mark_120_expired_in_1_days_subtask': {'queue': 'low', 'routing_key': 'low'},
    'run_entry_level_with_good_fdc_task': {'queue': 'low', 'routing_key': 'low'},
    'run_auto_retrofix_task': {'queue': 'low', 'routing_key': 'low'},
    'bca_inquiry_subtask': {'queue': 'low', 'routing_key': 'low'},
    'bca_snap_inquiry_subtask': {'queue': 'low', 'routing_key': 'low'},
    # 'trigger_send_follow_up_100_on_6_hours_subtask': {'queue': 'low', 'routing_key': 'low'},
    'send_registration_and_document_digisign_task': {'queue': 'high', 'routing_key': 'high'},
    # 'run_fdc_request': {'queue': 'lower', 'routing_key': 'lower'},
    'installation_data_row_subtask': {'queue': 'low', 'routing_key': 'low'},
    # 'send_sms_reminder_138_subtask': {'queue': 'low', 'routing_key': 'low'},
    'send_pn_payment_subtask': {'queue': 'low', 'routing_key': 'low'},
    'update_data_early_payback_offer_subtask': {'queue': 'low', 'routing_key': 'low'},
    # 'update_email_history_status': {'queue': 'low', 'routing_key': 'low'},
    # 'send_sms_otp_token': {'queue': 'high', 'routing_key': 'high'},
    'loan_lender_approval_process_task': {'queue': 'high', 'routing_key': 'high'},
    'julo_one_lender_auto_approval_task': {'queue': 'high', 'routing_key': 'high'},
    'julo_one_disbursement_trigger_task': {'queue': 'high', 'routing_key': 'high'},
    'create_application_checklist_async': {'queue': 'application_normal',
                                           'routing_key': 'application_normal'},
    # 'check_passive_liveness_async': {'queue': 'high', 'routing_key': 'high'},
    # 'send_email_otp_token': {'queue': 'high', 'routing_key': 'high'},
    # 'send_reset_pin_email': {'queue': 'high', 'routing_key': 'high'},
    'send_reset_password_email': {'queue': 'high', 'routing_key': 'high'},
    'monitor_fdc_inquiry_job': {'queue': 'high', 'routing_key': 'high'},
    'generate_application_axiata_async': {'queue': 'application_high', 'routing_key': 'application_high'},
    'run_loan_halt_periodic_task': {'queue': 'grab_halt_queue', 'routing_key': 'grab_halt_queue'},
    'run_loan_resume_periodic_task': {'queue': 'grab_resume_queue',
                                      'routing_key': 'grab_resume_queue'},
    'send_grab_api_timeout_alert_slack': {'queue': 'send_grab_api_timeout_alert_slack',
                                          'routing_key': 'send_grab_api_timeout_alert_slack'},
    'pii_vault.tasks.backfill_node_by_pk': {'queue': 'back_fill_pii_vault',
                                                       'routing_key': 'back_fill_pii_vault'},
    'pii_vault.tasks.produce_backfill_task_for_page': {'queue': 'back_fill_pii_vault',
                                                       'routing_key': 'back_fill_pii_vault'},
}

CELERYBEAT_SCHEDULE = {
    'refresh-crm-dashboard-every-minute': {
        'task': 'juloserver.julo.tasks.refresh_crm_dashboard',
        'schedule': crontab(minute='*'),
    },
    'loan-and-payments--every-night': {
        'task': 'update_loans_on_141',
        'schedule': crontab(minute=1, hour=1),  # Right after midnight
    },

    'mark-offer-expired-every-night': {
        'task': 'juloserver.julo.tasks.mark_offer_expired',
        'schedule': crontab(minute=15, hour=0),
    },

    'mark-sphp-expired-every-night': {
        'task': 'juloserver.julo.tasks.mark_sphp_expired',
        'schedule': crontab(minute=30, hour=0),
    },

    'mark-sphp-expired-every-night-julo-one': {
        'task': 'mark_sphp_expired_julo_one',
        'schedule': crontab(minute=30, hour=0),
    },
    'mark-form-partial-expired': {
        'task': 'juloserver.julo.tasks.mark_form_partial_expired',
        'schedule': crontab(minute=45, hour=0),
    },

    'mark-120-expired-in-1-days': {
        'task': 'juloserver.julo.tasks.mark_120_expired_in_1_days',
        'schedule': crontab(minute=1, hour=21),
    },

    'send_pn_submit_document_every_morning': {
        'task': 'juloserver.julo.tasks.send_submit_document_reminder_am',
        'schedule': crontab(minute=1, hour=9),
    },

    'send_pn_submit_document_every_night': {
        'task': 'juloserver.julo.tasks.send_submit_document_reminder_pm',
        'schedule': crontab(minute=1, hour=21),
    },

    # 'send_pn_resubmission_request_every_morning': {
    #     'task': 'send_resubmission_request_reminder_am',
    #     'schedule': crontab(minute=2, hour=9),
    # },
    #
    # 'send_pn_resubmission_request_every_night': {
    #     'task': 'send_resubmission_request_reminder_pm',
    #     'schedule': crontab(minute=2, hour=21),
    # },

    'send_pn_phone_verification_every_morning': {
        'task': 'juloserver.julo.tasks.send_phone_verification_reminder_am',
        'schedule': crontab(minute=3, hour=9),
    },

    'send_pn_phone_verification_every_night': {
        'task': 'juloserver.julo.tasks.send_phone_verification_reminder_pm',
        'schedule': crontab(minute=3, hour=21),
    },

    'send_pn_accept_offer_every_morning': {
        'task': 'juloserver.julo.tasks.send_accept_offer_reminder_am',
        'schedule': crontab(minute=4, hour=9),
    },

    'send_pn_accept_offer_every_night': {
        'task': 'juloserver.julo.tasks.send_accept_offer_reminder_pm',
        'schedule': crontab(minute=4, hour=21),
    },

    'send_pn_sign_sphp_every_morning': {
        'task': 'juloserver.julo.tasks.send_sign_sphp_reminder_am',
        'schedule': crontab(minute=5, hour=9),
    },

    'send_pn_sign_sphp_every_night': {
        'task': 'juloserver.julo.tasks.send_sign_sphp_reminder_am',
        'schedule': crontab(minute=5, hour=21),
    },
    'trigger_application_status_expiration_every_night': {
        'task': 'juloserver.julo.tasks.trigger_application_status_expiration',
        'schedule': crontab(minute=10, hour=0),
    },

    'trigger_send_email_follow_up_daily': {
        'task': 'juloserver.julo.tasks.trigger_send_email_follow_up_daily',
        'schedule': crontab(minute=7, hour=13),
    },

    # 'trigger_send_follow_up_email_100_daily': {
    #     'task': 'juloserver.julo.tasks.trigger_send_follow_up_email_100_daily',
    #     'schedule': crontab(minute=8, hour=13),
    # },

    # 'checking_doku_payments_peridically': {
    #     'task': 'checking_doku_payments_peridically',
    #     'schedule': crontab(minute='*/30'),
    # },

    # 'check_data_integrity_async': {
    #     'task': 'check_data_integrity_async',
    #     'schedule': crontab(minute=0, hour='4,10,16,22'),
    # },

    # 'check_data_integrity_hourly_async': {
    #     'task': 'check_data_integrity_hourly_async',
    #     'schedule': crontab(minute=0),
    # },

    # 'trigger_robocall': {
    #     'task': 'trigger_robocall',
    #     'schedule': crontab(minute=30, hour='9')
    # },

    'reminder_activation_code': {
        'task': 'juloserver.julo.tasks.reminder_activation_code',
        'schedule': crontab(minute='*/30')
    },

    'trigger_application_status_131_expiration_every_10_PM': {
        'task': 'juloserver.julo.tasks.expire_application_status_131',
        'schedule': crontab(minute=0, hour=22)
    },
    'trigger_application_status_175_expiration_every_9_PM': {
        'task': 'juloserver.julo.tasks.expire_application_status_175',
        'schedule': crontab(minute=0, hour=21),
    },

    'send_pn_resubmission_request_24_and_30_hour_after_131': {
        'task': 'juloserver.julo.tasks.send_resubmission_request_reminder_pn',
        'schedule': crontab(minute=0, hour='*/1')
    },

    'reminder_email_application_status_105': {
        'task': 'juloserver.julo.tasks.reminder_email_application_status_105',
        'schedule': crontab(minute=1, hour=20)
    },

    'scheduled_reminder_push_notif_application_status_105': {
        'task': 'juloserver.julo.tasks.scheduled_reminder_push_notif_application_status_105',
        'schedule': crontab(minute=0, hour=[8, 12, 18])
    },

    'generate_credit_score': {
        'task': 'juloserver.apiv2.tasks.generate_credit_score',
        'schedule': crontab(minute=[15, 45], hour='*'),
    },

    'run_entry_level_with_good_fdc_task': {
        'task': 'juloserver.application_flow.tasks.run_entry_level_with_good_fdc_task',
        'schedule': crontab(minute=0, hour=22),
    },

    'run_auto_retrofix_task': {
        'task': 'juloserver.application_flow.tasks.run_auto_retrofix_task',
        'schedule': crontab(minute=0, hour=8),
    },

    'partner_daily_report_mailer': {
        'task': 'juloserver.julo.tasks.partner_daily_report_mailer',
        'schedule': crontab(minute=0, hour=3),
    },

    'scheduling_can_apply': {
        'task': 'juloserver.julo.tasks.scheduling_can_apply',
        'schedule': crontab(minute=0, hour=0),
    },

    'trigger_send_follow_up_100_on_6_hours': {
        'task': 'juloserver.julo.tasks.trigger_send_follow_up_100_on_6_hours',
        'schedule': crontab(minute=0, hour='*/6'),
    },

    'send_sms_reminder_138': {
        'task': 'juloserver.julo.tasks.send_sms_reminder_138',
        'schedule': crontab(minute=0, hour=11, day_of_week='1-5'),
    },

    'send_sms_reminder_175_daily_8am': {
        'task': 'juloserver.julo.tasks.send_sms_reminder_175_daily_8am',
        'schedule': crontab(minute=0, hour=8),
    },

    # 'trigger_automated_grab_status_change': {
    #     'task': 'trigger_automated_grab_status_change',
    #     'schedule': crontab(minute='*/5'),
    # },

    'update_all_call_records': {
        'task': 'update_all_call_records',
        'schedule': crontab(minute='15', hour='*/1'),  # hourly at 15 mins pass
    },

    'checking_disbursement_failed': {
        'task': 'checking_disbursement_failed',
        'schedule': crontab(minute=0, hour='*/2')
    },

    # 'mark_whatsapp_failed_robocall': {
    #     'task': 'mark_whatsapp_failed_robocall',
    #     'schedule': crontab(minute=0, hour=14)
    # },

    'send_voice_ptp_payment_reminder': {
        'task': 'juloserver.julo.services2.voice.send_voice_ptp_payment_reminder',
        'schedule': crontab(minute=0, hour=10)
    },

    # the function is not used anymore
    # based on jira link: https://juloprojects.atlassian.net/browse/ON-603
    # 'trigger_automated_status_165_to_170': {
    #     'task': 'trigger_automated_status_165_to_170',
    #     'schedule': crontab(minute='*/15'),
    # },

    'scheduled_application_status_info': {
        'task': 'juloserver.julo.tasks.scheduled_application_status_info',
        'schedule': crontab(minute=0, hour='*/1')
    },

    'filter_122_with_nexmo_auto_call_part1': {
        'task': 'juloserver.julo.tasks.filter_122_with_nexmo_auto_call',
        'schedule': crontab(minute=0, hour=8)
    },

    'filter_122_with_nexmo_auto_call_part2': {
        'task': 'juloserver.julo.tasks.filter_122_with_nexmo_auto_call',
        'schedule': crontab(minute=30, hour=13)
    },

    'filter_138_with_nexmo_auto_call': {
        'task': 'juloserver.julo.tasks.filter_138_with_nexmo_auto_call',
        'schedule': crontab(minute=0, hour=10)
    },

    # prefix in prod is still the old one, wait until the prefix is new
    #
    # 'prefix_notification_due_in_3_0_days': {
    #     'task': 'prefix_notification_due_in_3_0_days',
    #     'schedule': crontab(minute=0, hour=7),
    # },
    #
    # 'prefix_notification_due_in_1_days': {
    #     'task': 'prefix_notification_due_in_1_days',
    #     'schedule': crontab(minute=0, hour=10),
    # },

    'application_auto_expiration': {
        'task': 'juloserver.julo.tasks.application_auto_expiration',
        'schedule': crontab(minute=0, hour=0),
    },

    'predictive_missed_call_part1': {
        'task': 'juloserver.julo.tasks.filter_application_by_predictive_missed_call',
        'schedule': crontab(minute=0, hour=8),
    },
    'predictive_missed_call_part2': {
        'task': 'juloserver.julo.tasks.filter_application_by_predictive_missed_call',
        'schedule': crontab(minute=0, hour=11),
    },
    'predictive_missed_call_part3': {
        'task': 'juloserver.julo.tasks.filter_application_by_predictive_missed_call',
        'schedule': crontab(minute=0, hour=15),
    },

    'reset_stuck_predictive_missed_call_state': {
        'task': 'juloserver.julo.tasks.reset_stuck_predictive_missed_call_state',
        'schedule': crontab(minute=0, hour=0),
    },

    'check_signal_anomaly_workflow_id_null': {
        'task': 'juloserver.apiv2.tasks.check_signal_anomaly_workflow_id_null',
        'schedule': crontab(minute=0, hour="*/1"),
    },

    'checking_application_checklist': {
        'task': 'juloserver.julo.tasks.checking_application_checklist',
        'schedule': crontab(minute='*/30'),
    },

    # 'complete_form_reminder_pn': {
    #     'task': 'complete_form_reminder_pn',
    #     'schedule': crontab(minute=0, hour=11),
    # },

    'delete_empty_folder_image_upload': {
        'task': 'juloserver.julo.tasks.delete_empty_folder_image_upload',
        'schedule': crontab(minute=0, hour=0)

    },

    'update_statement_late_fee': {
        'task': 'update_statement_late_fee',
        'schedule': crontab(minute=0, hour=0),
    },

    'count_disbursemet_summary_paylter': {
        'task': 'count_disbursemet_summary_paylter',
        'schedule': crontab(minute=5, hour=0),
    },

    # 'run_send_warning_letter2': {
    #   'task': 'run_send_warning_letter2',
    #    'schedule': crontab(minute=0, hour=10),
    # },

    # 'run_send_warning_letter3': {
    #   'task': 'run_send_warning_letter3',
    #    'schedule': crontab(minute=0, hour=10),
    # },

    'statement_reminder_paylater': {
        'task': 'juloserver.paylater.tasks.statement_reminder_paylater',
        'schedule': crontab(day_of_month="2,7,10,27,28,30", hour=10, minute=0)
    },

    'statement_reverse_waive_late_fee_daily': {
        'task': 'statement_reverse_waive_late_fee_daily',
        'schedule': crontab(minute=50, hour=23)
    },
    # this is change base on https://juloprojects.atlassian.net/browse/AM-540
    'send_all_sms_on_bukalapak': {
        'task': 'juloserver.paylater.tasks.send_all_sms_on_bukalapak',
        'schedule': crontab(day_of_month="4,20,25", minute=0, hour=10)
    },

    'regenerate_freelance_agent_password_at_10pm': {
        'task': 'juloserver.julo.tasks2.agent_tasks.scheduled_regenerate_freelance_agent_password',
        'schedule': crontab(minute=0, hour=22),
    },

    'pending_disbursement_notification_task': {
        'task': 'pending_disbursement_notification_task',
        'schedule': crontab(minute=0, hour=[6, 9, 12, 15, 18, 21]),
    },

    'send_warning_message_balance_amount': {
        'task': 'send_warning_message_balance_amount',
        'schedule': crontab(minute="*/30"),
    },

    'send_notification_message_balance_amount': {
        'task': 'send_notification_message_balance_amount',
        'schedule': crontab(minute=0, hour=[8, 17], day_of_week='1-5'),
    },
    'statement_waive_late_fee_september_campaign_prep': {
        'task': 'statement_waive_late_fee_september_campaign_prep',
        'schedule': crontab(minute=0, hour=5, day_of_month=1, month_of_year=9)
    },
    'statement_reverse_waive_late_fee_september_campaign_prep': {
        'task': 'statement_reverse_waive_late_fee_september_campaign_prep',
        'schedule': crontab(minute=0, hour=5, day_of_month=16, month_of_year=9)
    },
    'update_application_status_code_129_to_139': {  # run every night, right after midnight
        'task': 'update_application_status_code_129_to_139',
        'schedule': crontab(minute=1, hour=1)
    },
    'stuck_auto_retry_disbursement_via_xfers_wiper': {
        'task': 'stuck_auto_retry_disbursement_via_xfers_wiper',
        'schedule': crontab(minute=0, hour='*/3')
    },
    'bucket_150_auto_expiration': {
        'task': 'juloserver.julo.tasks2.application_tasks.bucket_150_auto_expiration',
        'schedule': crontab(minute=0, hour=0),
    },
    'bca_inquiry_transaction_every_2_hours': {
        'task': 'bca_inquiry_transaction',
        'schedule': crontab(minute=0, hour='*/2')
    },
    'bca_inquiry_transaction_run_at_end_of_day': {
        'task': 'bca_inquiry_transaction',
        'schedule': crontab(minute=59, hour=23)
    },
    'bca_snap_inquiry_transaction_every_2_hours': {
        'task': 'juloserver.integapiv1.tasks2.bca_tasks.bca_snap_inquiry_transaction',
        'schedule': crontab(minute=0, hour='*/2')
    },
    'bca_snap_inquiry_transaction_run_at_end_of_day': {
        'task': 'juloserver.integapiv1.tasks2.bca_tasks.bca_snap_inquiry_transaction',
        'schedule': crontab(minute=59, hour=23)
    },
    # 'revert_primary_va_to_normal': {
    #     'task': 'revert_primary_va_to_normal',
    #     'schedule': crontab(minute=0, hour=1)
    # },
    'expired_application_147_for_digisign': {
        'task': 'juloserver.julo.tasks.expired_application_147_for_digisign',
        'schedule': crontab(minute=5, hour=0)
    },
    'populate_xid_lookup': {
        'task': 'populate_xid_lookup',
        'schedule': crontab(minute=0, hour='*/1'),
    },

    #update installations daily at midnight
    'update_installation_data': {
        'task': 'juloserver.julo.tasks.update_installation_data',
        'schedule': crontab(minute=10, hour=1)
    },

    #update uninstallations daily at midnight
    'update_uninstallation_data': {
        'task': 'update_uninstallation_data',
        'schedule': crontab(minute=1, hour=1)
    },
    # experimentally reactivated
    'run_fdc_api': {
        'task': 'juloserver.julo.tasks.run_fdc_api',
        'schedule': crontab(minute=0, hour=6)
    },
    'run_fdc_api_resume': {
        'task': 'juloserver.julo.tasks.run_fdc_api_resume',
        'schedule': crontab(minute=0, hour=7)
    },
    'run_fdc_for_failure_status': {
        'task': 'juloserver.julo.tasks.run_fdc_for_failure_status',
        'schedule': crontab(minute=0, hour='*/2')
    },
    'recreate_skiptrace': {
        'task': 'juloserver.julo.tasks.recreate_skiptrace',
        'schedule': crontab(minute='*/30')
    },
    'populate_virtual_account_suffix': {
        'task': 'populate_virtual_account_suffix',
        'schedule': crontab(minute=25, hour=1, day_of_week='5')
    },
    'populate_mandiri_virtual_account_suffix': {
        'task': 'juloserver.julo.tasks.populate_mandiri_virtual_account_suffix',
        'schedule': crontab(minute=25, hour=1, day_of_week='5')
    },
    'populate_bni_virtual_account_suffix': {
        'task': 'juloserver.julo.tasks.populate_bni_virtual_account_suffix',
        'schedule': crontab(minute=25, hour=1, day_of_week='5')
    },
    'rerun_update_status_apps_flyer_task': {
        'task': 'juloserver.julo.tasks.rerun_update_status_apps_flyer_task',
        'schedule': crontab(minute='*/30')
    },
    'risk_customer_early_payoff_campaign': {
        'task': 'juloserver.julo.tasks2.campaign_tasks.risk_customer_early_payoff_campaign',
        'schedule': crontab(minute=0, hour=8)
    },
    'send_email_early_payoff_campaign_on_8_am': {
        'task': 'juloserver.julo.tasks2.campaign_tasks.send_email_early_payoff_campaign_on_8_am',
        'schedule': crontab(minute=0, hour=8)
    },
    'send_email_early_payoff_campaign_on_10_am': {
        'task': 'juloserver.julo.tasks2.campaign_tasks.send_email_early_payoff_campaign_on_10_am',
        'schedule': crontab(minute=0, hour=10)
    },
    'send_reminder_email_opt': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.send_reminder_email_opt',
        'schedule': crontab(minute=5, hour=8)
    },
    'expired_refinancing_request': {
        'task': 'juloserver.loan_refinancing.tasks.schedule_tasks.set_expired_refinancing_request',
        'schedule': crontab(minute=0, hour=4)
    },
    # change status to expired for R1-R3 cohort campaign on requested status
    'expired_refinancing_request_on_requested_status': {
        'task': 'juloserver.loan_refinancing.tasks.schedule_tasks'
                '.set_expired_refinancing_request_from_requested_status_with_campaign',
        'schedule': crontab(minute=0, hour=4)
    },
    'check_early_payback_offer_data': {
        'task': 'check_early_payback_offer_data',
        'schedule': crontab(minute=0, hour=8)
    },
    'update_minimum_income_for_pre_long_form_pop_up': {
        'task': 'update_minimum_income_for_pre_long_form_pop_up',
        'schedule': crontab(minute=0, hour='3'),
    },
    'trigger_google_analytics_data_download': {
        'task': 'juloserver.google_analytics.tasks.trigger_google_analytics_data_download',
        'schedule': crontab(minute=0, hour=11)
    },
    'trigger_retry_failed_download_google_analytics_data': {
        'task': 'juloserver.google_analytics.tasks'
                '.trigger_retry_failed_download_google_analytics_data',
        'schedule': crontab(minute=0, hour=10)
    },
    # 'reactivate_account_after_suspended_task': {
    #     'task': 'juloserver.account.tasks.scheduled_tasks
    #     .reactivate_account_after_suspended_task',
    #     'schedule': crontab(minute=0, hour=5),
    # },
    'update_is_5_days_unreachable': {
        'task': 'update_is_5_days_unreachable',
        'schedule': crontab(minute=0, hour=18)
    },
    # 'high_score_131_or_132_move_to_124_or_130': {
    #     'task': 'juloserver.julo.tasks2.application_tasks.high_score_131_or_132_move_to_124_or_130',
    #     'schedule': crontab(minute=0, hour='*/3')
    # },
    # 'interval_update_payment_bucket_count': {     # Deprecated
    #     'task': 'interval_update_payment_bucket_count',
    #     'schedule': crontab(minute='*/5',)
    # },
    'bonza_rescore_5xx_hit_asynchronously': {
        'task': 'juloserver.fraud_score.tasks.bonza_rescore_5xx_hit_asynchronously',
        'schedule': crontab(minute=0, hour=1)
    },
    'check_emails_sign_sphp_merchant_financing_expired': {
        'task': 'check_emails_sign_sphp_merchant_financing_expired',
        'schedule': crontab(minute=20, hour=0),
    },
    'claim_cfs_action_assignment': {
        'task': 'juloserver.cfs.tasks.claim_cfs_action_assignment',
        'schedule': crontab(minute=15, hour=0)
    },
    'check_cfs_action_expired': {
        'task': 'juloserver.cfs.tasks.check_cfs_action_expired',
        'schedule': crontab(minute=0, hour=2)
    },
    'send_email_efishery_account_payments_report': {
        'task': 'send_email_efishery_account_payments_report',
        'schedule': crontab(minute=0, hour=8)
    },
    # 'notify_dukcapil_asliri_remaining_balance': {
    #     'task': 'notify_dukcapil_asliri_remaining_balance',
    #     'schedule': crontab(minute=0, hour=7)
    # },
    # 'expired_application_emulator_check': {
    #     'task': 'juloserver.julo.tasks2.application_tasks.expired_application_emulator_check',
    #     'schedule': crontab(minute=0, hour='*/3')
    # },
    # TODO: turn off temporary
    'upload_axiata_disbursement_and_repayment_data_to_oss': {
        'task': 'upload_axiata_disbursement_and_repayment_data_to_oss',
        'schedule': crontab(minute=3, hour=1)
    },
    'google-calendar-payment-reminder': {
        'task': 'juloserver.minisquad.tasks2.google_calendar_task.google_calendar_payment_reminder',
        'schedule': crontab(minute=0, hour=17),
    },
    'check_loan_credit_card_stuck': {
        'task': 'juloserver.credit_card.tasks.transaction_tasks.check_loan_credit_card_stuck',
        'schedule': crontab(minute=59, hour=23)
    },
    # 'google-calendar-ptp-payment-reminder': {
    #     'task': 'juloserver.minisquad.tasks2.google_calendar_task
    #     .set_google_calendar_payment_reminder_by_account_payment_id',
    #     'schedule': crontab(minute=5, hour=17),
    # },
    # 'collect_loans_for_lendeast': {
    #     'task': 'juloserver.lendeast.tasks.collect_loans_for_lendeast',
    #     'schedule': crontab(minute=0, hour=3, day_of_month=1),
    # },
    'send_notification_reminders_to_klop_customer': {
        'task': 'send_notification_reminders_to_klop_customer',
        'schedule': crontab(minute=0, hour=8),
    },
    # 'daily_deactivate_pusdafil': {
    #     'task': 'juloserver.pusdafil.tasks.task_daily_deactivate_pusdafil',
    #     'schedule': crontab(hour=0, minute=0),
    # },
    # 'daily_activate_pusdafil': {
    #     'task': 'juloserver.pusdafil.tasks.task_daily_activate_pusdafil',
    #     'schedule': crontab(hour=2, minute=0),
    # },
    'update_gopay_balance_task': {
        'task': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_task',
        'schedule': crontab(hour=23, minute=0)
    },
    'daily_checker_loan_tagging_task': {
        'task': 'juloserver.channeling_loan.tasks.daily_checker_loan_tagging_task',
        'schedule': crontab(minute=0, hour='*/3')
    },
    'daily_checker_loan_tagging_clone_task': {
        'task': 'juloserver.channeling_loan.tasks.daily_checker_loan_tagging_clone_task',
        'schedule': crontab(minute=0, hour=6)
    },
    'cron_trigger_reconciliation_channeling_loan_task': {
        'task': 'juloserver.channeling_loan.tasks.reconciliation_channeling_loan_task',
        'schedule': crontab(minute=0, hour=11, day_of_month=1)
    },
    'gopay_autodebet_retry_mechanism': {
        'task': 'juloserver.payback.tasks.gopay_tasks.gopay_autodebet_retry_mechanism',
        'schedule': crontab(hour=19, minute=0)
    },
    'update_overlap_subscription': {
        'task': 'juloserver.payback.tasks.gopay_tasks.update_overlap_subscription',
        'schedule': crontab(hour=23, minute=0)
    },
    'run_task_dynamic_entry_level': {
        'task': 'juloserver.application_flow.tasks.run_task_dynamic_entry_level',
        'schedule': crontab(hour=14, minute=0)
    },
    'delete_old_customers': {
        'task': 'juloserver.application_flow.tasks.delete_old_customers',
        'schedule': crontab(hour=22, minute=0)
    },
    # 'run_retroload_bpjs_no_fdc_entry_level': {
    #     'task': 'juloserver.application_flow.tasks.run_retroload_bpjs_no_fdc_entry_level',
    #     'schedule': crontab(hour=21, minute=0)
    # },
    'check_payment_gateway_vendor_balance': {
        'task': 'check_payment_gateway_vendor_balance',
        'schedule': crontab(minute=0, hour='*/3')
    },
    'check_disbursement_status_schedule': {
        'task': 'check_disbursement_status_schedule',
        'schedule': crontab(minute=0, hour='*/3')
    },
    'retry_ayoconnect_loan_212': {
        'task': 'juloserver.loan.tasks.lender_related.retry_ayoconnect_loan_stuck_at_212_task',
        'schedule': crontab(minute=0, hour='*/6')
    },
    'payment_gateway_api_log_archival_task': {
        'task': 'juloserver.disbursement.tasks.payment_gateway_api_log_archival_task',
        'schedule': crontab(minute=30, hour=0)
    },
    'revive_shopee_whitelist_el': {
        'task': 'juloserver.application_flow.tasks.revive_shopee_whitelist_el',
        'schedule': crontab(hour=22, minute=0)
    },
    'daily_bank_statement_process': {
        'task': 'juloserver.application_flow.tasks.task_daily_bank_statement_process',
        'schedule': crontab(hour=0, minute=0)
    },
    'send_alert_for_stuck_loan_through_slack_task': {
        'task': 'juloserver.loan.tasks.send_alert_for_stuck_loan_through_slack_task',
        'schedule': crontab(minute='*/30')
    },
    'reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve': {
        'task': 'juloserver.loan.tasks.lender_related.reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task',
        'schedule': crontab(minute=0, hour='*')
    },
    'back_fill_onboarding_pii_vault': {
        'task': 'juloserver.pii_vault.tasks.back_fill_onboarding_pii_vault',
        'schedule': crontab(minute=0, hour=[4, 5, 6])
    },
    'recover_pii_vault_event': {
        'task': 'juloserver.pii_vault.tasks.recover_pii_vault_event',
        'schedule': crontab(minute=0, hour='0-3,7-23'),
    },
    'fdc_inquiry_for_active_loan_from_platform_daily_checker_task': {
        'task': 'juloserver.loan.tasks.lender_related'
                '.fdc_inquiry_for_active_loan_from_platform_daily_checker_task',
        'schedule': crontab(hour=3, minute=0)
    },
    'send_sms_to_user_at_100_and_will_expire_in_1_day': {
        'task': 'juloserver.grab.tasks.send_sms_to_user_at_100_and_will_expire_in_1_day',
        'schedule': crontab(minute=0, hour='*')
    },
    'send_sms_to_user_at_131_for_24_hour': {
        'task': 'juloserver.grab.tasks.send_sms_to_user_at_131_for_24_hour',
        'schedule': crontab(minute=0, hour='*'),
    },
    'send_email_to_user_at_131_for_24_hour': {
        'task': 'juloserver.grab.tasks.send_email_to_user_at_131_for_24_hour',
        'schedule': crontab(minute=0, hour='*')
    },
    'send_email_to_user_before_3hr_of_app_expire': {
        'task': 'juloserver.grab.tasks.send_email_to_user_before_3hr_of_app_expire',
        'schedule': crontab(minute=0, hour='*')
    },
    'initial_retroload_dragon_ball': {
        'task': 'juloserver.application_flow.tasks.initial_retroload_dragon_ball',
        'schedule': crontab(hour=8, minute=50),
        'options': {
            'expires': 7200.0,
        }
    },
    'grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task': {
        'task': 'juloserver.grab.tasks.grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task',
        'schedule': crontab(hour=9, minute=0)
    },
    'grab_app_stuck_150_handler_task': {
        'task': 'juloserver.grab.tasks.grab_app_stuck_150_handler_task',
        'schedule': crontab(hour='*', minute=0)
    },
    'batch_send_daily_credgenics_csv': {
        'task': 'juloserver.credgenics.tasks.loans.batch_send_daily_credgenics_csv',
        'schedule': crontab(hour=2, minute=0),
    },
    # 'pn_blast_scheduler_for_product_picker_issue': {
    #     'task': 'juloserver.application_flow.tasks.pn_blast_scheduler_for_product_picker_issue',
    #     'schedule': crontab(minute=0, hour=[10, 14, 19]),
    # },
    'grab_emergency_contact_tasks': {
        'task': 'juloserver.grab.tasks.task_emergency_contact',
        'schedule': crontab(hour='*', minute=0),
    },
    'cimb_payment_status_transaction': {
        'task': 'juloserver.payback.tasks.cimb_va_tasks.cimb_payment_status_transaction',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    'grab_emergency_contact_tasks_resend_sms': {
        'task': 'juloserver.grab.tasks.task_emergency_contact_resend_sms',
        'schedule': crontab(hour='*', minute=0),
    },
    'daily_repayment_for_waive_principle_and_refinancing_credgenics': {
        'task': 'juloserver.credgenics.tasks.loans.daily_repayment_for_waive_principle_and_refinancing_credgenics',
        'schedule': crontab(hour=8, minute=0),
    },
    'retry_anti_fraud_binary_checks': {
        'task': 'juloserver.application_flow.tasks.retry_anti_fraud_binary_checks',
        'schedule': crontab(minute='*/30'),
    },
    'faspay_snap_inquiry_payment_status_every_2_hours': {
        'task': 'juloserver.account_payment.tasks.repayment_tasks.faspay_snap_inquiry_transaction',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    'doku_snap_inquiry_payment_status_every_2_hours': {
        'task': 'juloserver.account_payment.tasks.repayment_tasks.doku_snap_inquiry_transaction',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    'populate_fama_loan_after_cutoff': {
        'task': 'juloserver.channeling_loan.tasks.populate_fama_loan_after_cutoff',
        'schedule': crontab(minute='45', hour='14'),
    },
    'ovo_tokenization_inquiry_payment_status_every_2_hours': {
        'task': 'juloserver.account_payment.tasks.repayment_tasks.ovo_tokenization_inquiry_transaction',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    'refresh_access_token': {
        'task': 'juloserver.payment_gateway.tasks.refresh_access_token',
        'schedule': crontab(minute='*/10'),
    },
    'recheck_transfer_status': {
        'task': 'juloserver.payment_gateway.tasks.recheck_transfer_status',
        'schedule': crontab(minute=0, hour='*/1'),
        'args': (Vendor.DOKU.value,),
    },
    'repopulate_zipcode_scheduler': {
        'task': 'juloserver.application_form.tasks.application_task.repopulate_zipcode',
        'schedule': crontab(minute=0, hour=4),
    },
    'retry_send_callback_url': {
        'task': 'juloserver.payment_gateway.tasks.retry_send_callback_url',
        'schedule': crontab(minute=0, hour='*/1'),
    },
    'hit_fdc_for_rejected_customers': {
        'task': 'juloserver.application_flow.tasks.hit_fdc_for_rejected_customers',
        'schedule': crontab(hour=10, minute=0),
    },
}

CELERYBEAT_SCHEDULE.update(COLLECTION_CELERYBEAT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(LOAN_REFINANCING_CELERYBEAT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(PROMO_CAMPAIGN_CELERYBEAT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(MOENGAGE_UPLOAD_CELERYBEAT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(FDC_CELERYBEAT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(AUTODEBET_SCHEDULE)
CELERYBEAT_SCHEDULE.update(SALES_OPS_SCHEDULE)
CELERYBEAT_SCHEDULE.update(JULOVERS_SCHEDULE)
CELERYBEAT_SCHEDULE.update(CHANNELING_SCHEDULE)
CELERYBEAT_SCHEDULE.update(ACCOUNT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(ACCOUNT_PAYMENT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(DISBURSEMENT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(FOLLOWTHEMONEY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(PAYMENT_POINT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(LENDERINVESTMENT_SCHEDULE)
CELERYBEAT_SCHEDULE.update(COLLECTION_HI_SEASON_CELERY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(CASHBACK_CELERY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(GRADUATION_SCHEDULE)
CELERYBEAT_SCHEDULE.update(DANA_SCHEDULE)
CELERYBEAT_SCHEDULE.update(OVO_SCHEDULE)
CELERYBEAT_SCHEDULE.update(JULO_STARTER_SCHEDULE)
CELERYBEAT_SCHEDULE.update(FRAUD_SECURITY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(EDUCATION_SCHEDULE)
CELERYBEAT_SCHEDULE.update(MERCHANT_FINANCING_SCHEDULE)
CELERYBEAT_SCHEDULE.update(PROMO_CMS_SCHEDULE)
CELERYBEAT_SCHEDULE.update(IN_APP_ACCOUNT_DELETION_CELERY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(ACCOUNT_DELETION_CELERY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(DANA_LINKING_SCHEDULE)
CELERYBEAT_SCHEDULE.update(IN_APP_ACCOUNT_DELETION_CELERY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(PRODUCT_FINANCING_SCHEDULE)
CELERYBEAT_SCHEDULE.update(LOAN_SCHEDULE)
CELERYBEAT_SCHEDULE.update(POPULATE_CUSTOMER_XID_CELERY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(RETROFIX_DELETED_APPLICATION_186_SCHEDULE)
CELERYBEAT_SCHEDULE.update(PARTNERSHIP_SCHEDULE)
CELERYBEAT_SCHEDULE.update(LOYALTY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(OMNICHANNEL_SCHEDULE)
CELERYBEAT_SCHEDULE.update(RETROFIX_OLD_DELETION_DATA_SCHEDULE)
CELERYBEAT_SCHEDULE.update(PAYBACK_SCHEDULE)
CELERYBEAT_SCHEDULE.update(ONEKLIK_SCHEDULE)
CELERYBEAT_SCHEDULE.update(BALANCE_CONSOLIDATION_SCHEDULE)
CELERYBEAT_SCHEDULE.update(MINISQUAD_SCHEDULE)
CELERYBEAT_SCHEDULE.update(SALES_OPS_PDS_SCHEDULE)
CELERYBEAT_SCHEDULE.update(CLEANUP_PAYDAY_CHANGE_REQUEST_FROM_REDIS_SCHEDULE)
CELERYBEAT_SCHEDULE.update(REFERRAL_SCHEDULE)
CELERYBEAT_SCHEDULE.update(AUTO_APPROVAL_CONSENT_WITHDRAWAL_CELERY_SCHEDULE)
CELERYBEAT_SCHEDULE.update(LEADGEN_WEBAPP_RESUME_APPLICATION_STUCK_105)
