from celery.schedules import crontab


DANA_LINKING_SCHEDULE = {
    'update_dana_balance': {
        'task': 'juloserver.dana_linking.tasks.update_dana_balance',
        'schedule': crontab(minute=30, hour=4),
    },
}
