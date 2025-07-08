from celery.schedules import crontab

CASHBACK_CELERY_SCHEDULE = {
    'system_used_on_payment_dpd': {
        'task': 'juloserver.cashback.tasks.system_used_on_payment_dpd',
        'schedule': crontab(minute=0, hour=23)
    },
    'use_cashback_payment_and_expiry_cashback': {
        'task': 'juloserver.cashback.tasks.use_cashback_payment_and_expiry_cashback',
        'schedule': crontab(minute=0, hour=0, day_of_month=31, month_of_year=12)
    },
    'unfreeze_referral_cashback': {
        'task': 'juloserver.cashback.tasks.unfreeze_referral_cashback',
        'schedule': crontab(minute=0, hour=1, day_of_month='1-31', month_of_year='1-2')
    },
    # Execute on 25th every month at 00:00
    'inject_cashback_promo_task': {
        'task': 'juloserver.cashback.tasks.inject_cashback_promo_task',
        'schedule': crontab(minute=0, hour=0, day_of_month=25),
    },
}
