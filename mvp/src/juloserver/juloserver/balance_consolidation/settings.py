from celery.schedules import crontab

BALANCE_CONSOLIDATION_SCHEDULE = {
    'juloserver.balance_consolidation.tasks.fetch_balance_consolidation_fdc_data': {
        'task': 'juloserver.balance_consolidation.tasks.fetch_balance_consolidation_fdc_data',
        'schedule': crontab(minute=0, hour=5),
    }
}
