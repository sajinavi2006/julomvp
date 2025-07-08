from celery.schedules import crontab


EDUCATION_SCHEDULE = {
    "health_check_redis_for_school_searching": {
        "task": "juloserver.education.tasks.health_check_redis_for_school_searching",
        "schedule": crontab(minute="*/5"),
    },
}
