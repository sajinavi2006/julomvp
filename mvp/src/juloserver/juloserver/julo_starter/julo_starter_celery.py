from celery.schedules import crontab

JULO_STARTER_SCHEDULE = {
    'trigger_form_partial_expired_julo_starter': {
        'task': 'juloserver.julo_starter.tasks.app_tasks.trigger_form_partial_expired_julo_starter',
        'schedule': crontab(minute=45, hour=0),
    },
    'enable_reapply_for_rejected_external_check': {
        'task': (
            'juloserver.julo_starter.tasks.app_tasks.enable_reapply_for_rejected_external_check'
        ),
        'schedule': crontab(minute=50, hour=0),
    },
    'trigger_revert_application_upgrade': {
        'task': ('juloserver.julo_starter.tasks.app_tasks.trigger_revert_application_upgrade'),
        'schedule': crontab(minute=0, hour=1),
    },
}
