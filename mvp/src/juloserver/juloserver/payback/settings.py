from celery.schedules import crontab

PAYBACK_SCHEDULE = {
    'populate_doku_virtual_account_suffix': {
        'task': 'juloserver.payback.tasks.doku_tasks.populate_doku_virtual_account_suffix',
        'schedule': crontab(minute=25, hour=1, day_of_week='5'),
    },
}
