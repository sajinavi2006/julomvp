from celery.schedules import crontab


REFERRAL_SCHEDULE = {
    # Run every day at 00:00
    'juloserver.referral.tasks.refresh_top_referral_cashbacks_cache': {
        'task': 'juloserver.referral.tasks.refresh_top_referral_cashbacks_cache',
        'schedule': crontab(minute=0, hour=0),
    },
}
