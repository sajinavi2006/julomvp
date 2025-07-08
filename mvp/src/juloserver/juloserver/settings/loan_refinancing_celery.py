from celery.schedules import crontab

LOAN_REFINANCING_CELERYBEAT_SCHEDULE = {
    'notify_eligible_customers_for_loan_refinancing': {
        'task': 'juloserver.loan_refinancing.tasks.notification_tasks.notify_eligible_customers_for_loan_refinancing',
        'schedule': crontab(minute=0, hour=8)
    },
}
