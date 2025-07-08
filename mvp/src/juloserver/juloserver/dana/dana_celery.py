from datetime import timedelta

from celery.schedules import crontab

DANA_SCHEDULE = {
    # Ai Rudder
    'generate_data_for_dialer': {
        'task': 'juloserver.dana.collection.tasks.populate_dana_dialer_temp_data',
        'schedule': crontab(minute=0, hour=2),
    },
    'merge_dana_dialer_temporary_data': {
        'task': 'juloserver.dana.collection.tasks.merge_dana_dialer_temporary_data',
        'schedule': crontab(minute=0, hour=3),
    },
    'dana_construct_call_data_dialer_bucket_all': {
        'task': 'juloserver.dana.collection.tasks.dana_construct_call_data_dialer_bucket_all',
        'schedule': crontab(minute=45, hour=4),
    },
    'dana_trigger_upload_data_to_dialer': {
        'task': 'juloserver.dana.collection.tasks.dana_trigger_upload_data_to_dialer',
        'schedule': crontab(minute=0, hour=6, day_of_week='1-6'),
    },
    'dana_trigger_slack_notification_for_empty_bucket': {
        'task': 'juloserver.dana.collection.tasks.dana_trigger_slack_notification_for_empty_bucket',
        'schedule': crontab(minute=0, hour=7, day_of_week='1-6'),
    },
    'dana_consume_call_result_system_level': {
        'task': 'juloserver.dana.collection.tasks.dana_consume_call_result_system_level',
        'schedule': crontab(
            minute=15, hour=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], day_of_week='1-6'
        ),
    },
    'dana_flush_payload_dialer_data': {
        'task': 'juloserver.dana.collection.tasks.dana_flush_payload_dialer_data',
        'schedule': crontab(minute=0, hour=22),
    },
    # End of Ai Rudder
    'flush_dana_temp_data_for_dialer': {
        'task': 'juloserver.dana.collection.tasks.flush_dana_temp_data_for_dialer',
        'schedule': crontab(minute=0, hour=21),
    },
    'trigger_update_late_fee_amount': {
        'task': 'juloserver.dana.repayment.tasks.trigger_update_late_fee_amount',
        'schedule': crontab(minute=0, hour=1),
    },
    'upload_dana_t0_data_to_intelix': {
        'task': 'juloserver.dana.collection.tasks.upload_dana_t0_cootek_data_to_intelix',
        'schedule': crontab(minute=30, hour=11),
    },
    'process_pending_dana_repayment_task': {
        'task': 'juloserver.dana.repayment.tasks.process_pending_dana_repayment_task',
        'schedule': crontab(minute=0, hour=[7, 18]),
    },
    'process_pending_dana_payment_task': {
        'task': 'juloserver.dana.loan.tasks.process_pending_dana_payment_task',
        'schedule': crontab(minute=0, hour="*/1"),
    },
    'fill_empty_marital_status_dana': {
        'task': 'juloserver.dana.tasks.fill_empty_marital_status_dana',
        'schedule': crontab(minute=0, hour=8),
    },
    'recalculate_account_limit': {
        'task': 'juloserver.dana.loan.tasks.recalculate_account_limit',
        'schedule': crontab(minute=59, hour=[23, 17]),
    },
    'process_pending_dana_refund_task': {
        'task': 'juloserver.dana.refund.tasks.process_pending_dana_refund_task',
        'schedule': crontab(minute=0, hour="*/3"),
    },
    'trigger_resume_dana_loan_stuck_211': {
        'task': 'juloserver.dana.tasks.trigger_resume_dana_loan_stuck_211',
        'schedule': crontab(minute=0, hour='*/1'),
    },
    'auto_generate_dana_loan_agreement': {
        'task': 'juloserver.dana.tasks.auto_generate_dana_loan_agreement',
        'schedule': crontab(minute=0, hour=8),
    },
    'resend_dana_fdc_result': {
        'task': 'juloserver.dana.tasks.resend_dana_fdc_result',
        'schedule': crontab(minute=0, hour="*/1"),
    },
    'check_dana_loan_stuck_211_payment_consult_flow': {
        'task': 'juloserver.dana.tasks.check_dana_loan_stuck_211_payment_consult_flow',
        'schedule': timedelta(seconds=30),
    },
    'trigger_resume_dana_application_stuck': {
        'task': 'juloserver.dana.tasks.trigger_resume_dana_application_stuck',
        'schedule': crontab(minute=0, hour="*/1"),
    },
}
