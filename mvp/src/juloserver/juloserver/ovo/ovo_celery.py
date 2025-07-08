from celery.schedules import crontab

OVO_SCHEDULE = {
    'ovo_balance_inquiry': {
        'task': 'juloserver.ovo.tasks.ovo_balance_inquiry',
        'schedule': crontab(minute=0, hour=3),
    },
}
