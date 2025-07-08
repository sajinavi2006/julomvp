from celery.schedules import crontab

PROMO_CAMPAIGN_CELERYBEAT_SCHEDULE = {
    'send_ramadan_email_campaign': {
        'task': 'send_ramadan_email_campaign',
        'schedule': crontab(minute=0, hour=8),
    },
    'send_ramadan_pn_campaign': {
        'task': 'send_ramadan_pn_campaign',
        'schedule': crontab(minute=30, hour=13),
    },
    'send_ramadan_sms_campaign': {
        'task': 'send_ramadan_sms_campaign',
        'schedule': crontab(minute=0, hour=19)
    },
    'trigger_reward_cashback_for_limit_usage': {
        'task': 'juloserver.loan.tasks.campaign.trigger_reward_cashback_for_limit_usage',
        'schedule': crontab(minute=0, hour=23)
    }

}
