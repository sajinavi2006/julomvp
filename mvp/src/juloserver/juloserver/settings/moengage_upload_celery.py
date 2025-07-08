from celery.schedules import crontab

MOENGAGE_UPLOAD_CELERYBEAT_SCHEDULE = {
    'trigger_update_moengage_for_scheduled_application_status_change_events': {
        'task': 'juloserver.moengage.tasks.trigger_update_moengage_for_scheduled_application_status_change_events',
        'schedule': crontab(minute=1, hour=0)
    },
    'trigger_bulk_update_moengage_for_scheduled_loan_status_change_210': {
        'task': 'juloserver.moengage.tasks.trigger_bulk_update_moengage_for_scheduled_loan_status_change_210',
        'schedule': crontab(minute=1, hour=0)
    },
    'trigger_to_update_data_on_moengage': {
        'task': 'juloserver.moengage.tasks.trigger_to_update_data_on_moengage',
        'schedule': crontab(minute=1, hour=0)
    },
    'trigger_to_push_churn_data_on_moengage': {
        'task': 'juloserver.moengage.tasks.trigger_to_push_churn_data_on_moengage',
        'schedule': crontab(minute=1, hour=7)  # At (GMT+7)
    },
    'daily_update_customer_segment_data_on_moengage': {
        'task': 'juloserver.moengage.tasks.daily_update_customer_segment_data_on_moengage',
        'schedule': crontab(minute=1, hour=8)
    },
    'daily_update_sign_master_agreement_qris': {
        'task': 'juloserver.moengage.tasks.daily_update_sign_master_agreement_qris',
        'schedule': crontab(minute=1, hour=6)
    },
}
