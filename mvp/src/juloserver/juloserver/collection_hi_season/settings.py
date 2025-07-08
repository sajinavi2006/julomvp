from celery.schedules import crontab

COLLECTION_HI_SEASON_CELERY_SCHEDULE = {
    'trigger_update_collection_hi_season_campaign_status': {
        'task': 'juloserver.collection_hi_season.tasks.'
        'trigger_update_collection_hi_season_campaign_status',
        'schedule': crontab(minute=1, hour=0),
    },
    'trigger_run_collection_hi_season_campaign': {
        'task': 'juloserver.collection_hi_season.tasks.trigger_run_collection_hi_season_campaign',
        'schedule': crontab(minute=30, hour=0),
    },
}
