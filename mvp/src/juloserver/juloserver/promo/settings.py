from celery.schedules import crontab

PROMO_CMS_SCHEDULE = {
    'juloserver.promo.tasks.fetch_promo_cms': {
        'task': 'juloserver.promo.tasks.fetch_promo_cms',
        'schedule': crontab(minute='*/10'),
    },
    'juloserver.promo.tasks.reset_promo_code_daily_usage_count': {
        'task': 'juloserver.promo.tasks.reset_promo_code_daily_usage_count',
        'schedule': crontab(minute=0, hour=0),
    },
    'juloserver.promo.tasks.upload_whitelist_customers_data_for_raven_experiment': {
        'task': 'juloserver.promo.tasks.upload_whitelist_customers_data_for_raven_experiment',
        'schedule': crontab(minute=0, hour=7),
    },
}
