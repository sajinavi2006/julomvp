from celery.schedules import crontab

IN_APP_ACCOUNT_DELETION_CELERY_SCHEDULE = {
    'inapp_account_deletion_deactivate_account_pending_status': {
        'task': 'juloserver.julo.tasks.inapp_account_deletion_deactivate_account_pending_status',
        'schedule': crontab(minute=0, hour=9),
    },
    'inapp_account_deletion_deactivate_account_approved_status': {
        'task': 'juloserver.julo.tasks.inapp_account_deletion_deactivate_account_approved_status',
        'schedule': crontab(minute=0, hour=9),
    }

}
