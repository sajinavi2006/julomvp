from celery.schedules import crontab

DISBURSEMENT_SCHEDULE = {
    'check_disbursement_via_bca': {
        'task': 'juloserver.disbursement.tasks.check_disbursement_via_bca',
        'schedule': crontab(minute=0, hour=0),
    },
    'auto_retry_disbursement_via_bca': {
        'task': 'juloserver.disbursement.tasks.auto_retry_disbursement_via_bca',
        'schedule': crontab(minute=0, hour='1,5,9,13,17,21'),
    },
    'bca_pending_status_check_in_170': {
        'task': 'juloserver.disbursement.tasks.bca_pending_status_check_in_170',
        'schedule': crontab(minute=0, hour='1,5,9,13,17,21'),
    },
    'check_gopay_balance_threshold': {
        'task': 'juloserver.disbursement.tasks.check_gopay_balance_threshold',
        'schedule': crontab(minute=0, hour='9,16'),
    }
}
