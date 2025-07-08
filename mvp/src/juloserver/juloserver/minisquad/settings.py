from celery.schedules import crontab

MINISQUAD_SCHEDULE = {
    'clear_dynamic_airudder_config': {
        'task': 'juloserver.minisquad.tasks2.dialer_system_task.clear_dynamic_airudder_config',
        'schedule': crontab(minute=0, hour=22),
    },
    'update_skiptrace_stats_task': {
        'task': 'juloserver.minisquad.tasks.update_skiptrace_stats_task',
        'schedule': crontab(minute=5, hour=0),
    },
}
