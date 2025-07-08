from celery.schedules import crontab

JULOVERS_SCHEDULE = {
    'juloserver.julovers.tasks.execute_julovers_repayment': {
        'task': 'juloserver.julovers.tasks.execute_julovers_repayment',
        'schedule': crontab(minute=0, hour=4, day_of_month="1,28,29,30,31"),
    },
    'sync-julover-vault-token':{
        'task': 'juloserver.julovers.tasks.sync_julover_vault_token_task',
        'schedule': crontab(minute=0, hour="*/4"),
    },
}
