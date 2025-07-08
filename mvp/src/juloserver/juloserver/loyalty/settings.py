from celery.schedules import crontab


LOYALTY_SCHEDULE = {
    'juloserver.loyalty.tasks.expire_point_earning_task': {
        'task': 'juloserver.loyalty.tasks.expire_point_earning_task',
        'schedule': crontab(minute=0, hour=0, day_of_month=1),
    },
    # Run every day at 00:00
    'juloserver.loyalty.tasks.expire_mission_config_task': {
        'task': 'juloserver.loyalty.tasks.expire_mission_config_task',
        'schedule': crontab(minute=0, hour=0),
    },
    # Run every day at 00:10
    'juloserver.loyalty.tasks.claim_mission_progress_after_repetition_delay_task': {
        'task': 'juloserver.loyalty.tasks.claim_mission_progress_after_repetition_delay_task',
        'schedule': crontab(minute=10, hour=0),
    },
    # Run every day at 0:00
    'juloserver.loyalty.tasks.send_loyalty_total_point_to_moengage_task': {
        'task': 'juloserver.loyalty.tasks.send_loyalty_total_point_to_moengage_task',
        'schedule': crontab(minute=0, hour=0),
    },
}
