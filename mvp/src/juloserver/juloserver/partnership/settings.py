from celery.schedules import crontab

PRODUCT_FINANCING_SCHEDULE = {
    'process_expired_skrtp_gosel': {
        'task': 'juloserver.partnership.tasks.process_expired_skrtp_gosel',
        'schedule': crontab(minute=0, hour=1),
    },
}

PARTNERSHIP_SCHEDULE = {
    'linkaja_handle_disbursement_failed': {
        'task': 'juloserver.partnership.tasks.linkaja_handle_disbursement_failed',
        'schedule': crontab(minute=0, hour=23),
    },
}

LEADGEN_WEBAPP_RESUME_APPLICATION_STUCK_105 = {
    'leadgen_webapp_resume_application_stuck_105': {
        'task': 'juloserver.partnership.tasks.rerun_leadgen_stuck_105',
        'schedule': crontab(minute=0, hour='*/6'),
    },
}
