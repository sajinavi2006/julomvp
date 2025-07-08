from celery.schedules import crontab


ACCOUNT_DELETION_CELERY_SCHEDULE = {
    'send_follow_up_deletion_request_email': {
        'task': (
            'juloserver.customer_module.tasks.'
            'account_deletion_tasks.send_follow_up_deletion_request_email'
        ),
        'schedule': crontab(minute=0, hour=20),  # everyday at 8PM
    },
}

POPULATE_CUSTOMER_XID_CELERY_SCHEDULE = {
    'populate_customer_xid': {
        'task': 'populate_customer_xid',
        'schedule': crontab(minute=0, hour=1),  # everyday at 1AM
    },
}

RETROFIX_DELETED_APPLICATION_186_SCHEDULE = {
    'update_deleted_application_status_to_186': {
        'task': (
            'juloserver.customer_module.tasks.'
            'account_deletion_tasks.update_deleted_application_status_to_186'
        ),
        'schedule': crontab(minute=0, hour=1),  # everyday at 1AM
    }
}

RETROFIX_OLD_DELETION_DATA_SCHEDULE = {
    'update_deletion_data_to_new_format': {
        'task': (
            'juloserver.customer_module.tasks.'
            'account_deletion_tasks.update_deletion_data_to_new_format'
        ),
        'schedule': crontab(minute=0, hour=2),  # everyday at 2AM
    }
}

CLEANUP_PAYDAY_CHANGE_REQUEST_FROM_REDIS_SCHEDULE = {
    'cleanup_payday_change_request_from_redis': {
        'task': (
            'juloserver.customer_module.tasks.'
            'customer_related_tasks.cleanup_payday_change_request_from_redis'
        ),
        'schedule': crontab(minute=0, hour=3),  # everyday at 3AM
    }
}

AUTO_APPROVAL_CONSENT_WITHDRAWAL_CELERY_SCHEDULE = {
    'auto_approval_consent_withdrawal': {
        'task': (
            'juloserver.customer_module.tasks.'
            'customer_related_tasks.auto_approval_consent_withdrawal'
        ),
        'schedule': crontab(minute=1, hour=0),  # everyday at 12AM
    }
}
