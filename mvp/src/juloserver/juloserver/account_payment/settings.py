from celery.schedules import crontab

ACCOUNT_PAYMENT_SCHEDULE = {
    'update-account-payment-status-every-night': {
        'task': 'juloserver.account_payment.tasks.scheduled_tasks.update_account_payment_status',
        'schedule': crontab(minute=1, hour=0),  # new J1 account payment
    },
    'pull-late-fee-earlier-every-night': {
        'task': 'juloserver.account_payment.tasks.scheduled_tasks.register_late_fee_experiment',
        'schedule': crontab(minute=0, hour=5),  # pull csv data from gdrive
    },
    'new-update-late-amount': {
        'task': 'juloserver.account_payment.tasks.scheduled_tasks.new_late_fee_generation_task',
        'schedule': crontab(minute=30, hour=0),
    },
    'expiry-cashback-claim-experiment': {
        'task': 'juloserver.account_payment.tasks.cashback_tasks.expiry_cashback_claim_experiment',
        'schedule': crontab(minute=30, hour=0),
    },
}
