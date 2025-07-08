from celery.schedules import crontab

AUTODEBET_SCHEDULE = {
    'collect_autodebet_account_collections_task': {
        'task': 'juloserver.autodebet.tasks.collect_autodebet_account_collections_task',
        'schedule': crontab(minute=0, hour="10,19")
    },
    'scheduled_pending_revocation_sweeper': {
        'task': 'juloserver.autodebet.tasks.scheduled_pending_revocation_sweeper',
        'schedule': crontab(minute=59, hour=23)
    },
    'scheduled_inquiry_account_registration': {
        'task': 'juloserver.autodebet.tasks.scheduled_inquiry_account_registration',
        'schedule': crontab(minute=0, hour="6,18",)
    },
    'collect_gopay_autodebet_account_collections_task': {
        'task': 'juloserver.autodebet.tasks.collect_gopay_autodebet_account_collections_task',
        'schedule': crontab(minute=0, hour="10")
    },
    'collect_and_update_gopay_autodebet_account_subscription_task': {
        'task': 'juloserver.autodebet.tasks'
                '.collect_and_update_gopay_autodebet_account_subscription_task',
        'schedule': crontab(minute=0, hour="10")
    },
    'collect_mandiri_autodebet_account_maximum_limit_collections_task': {
        'task': 'juloserver.autodebet.tasks'
                '.collect_mandiri_autodebet_account_maximum_limit_collections_task',
        'schedule': crontab(minute=0, hour="10,19")
    },
    'scheduled_pending_registration_sweeper_mandiri': {
        'task': 'juloserver.autodebet.tasks.scheduled_pending_registration_sweeper_mandiri',
        'schedule': crontab(minute=59, hour=23)
    },
    'inquiry_payment_autodebet_bri': {
        'task': 'juloserver.autodebet.tasks.inquiry_payment_autodebet_bri_scheduler',
        'schedule': crontab(minute=0, hour=10)
    },
    'collect_bni_autodebet_account_maximum_limit_collections_task': {
        'task': 'juloserver.autodebet.tasks'
                '.collect_bni_autodebet_account_maximum_limit_collections_task',
        'schedule': crontab(minute=0, hour="10,19")
    },
    'reinquiry_payment_autodebet_bni': {
        'task': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_bni_scheduler',
        'schedule': crontab(minute=0, hour=10),
    },
    'scheduled_pending_registration_sweeper_bni': {
        'task': 'juloserver.autodebet.tasks.scheduled_pending_registration_sweeper_bni',
        'schedule': crontab(minute=59, hour="23,5,11,17"),
    },
    'collect_dana_autodebet_account_collection_task': {
        'task': 'juloserver.autodebet.tasks.collect_dana_autodebet_account_collection_task',
        'schedule': crontab(minute=0, hour="10, 19"),
    },
    'reinquiry_payment_autodebet_dana': {
        'task': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_dana_scheduler',
        'schedule': crontab(minute=0, hour=10),
    },
    'reinquiry_payment_autodebet_ovo': {
        'task': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_ovo_scheduler',
        'schedule': crontab(minute=0, hour=10),
    },
    'collect_ovo_autodebet_account_collection_task': {
        'task': 'juloserver.autodebet.tasks.collect_ovo_autodebet_account_collection_task',
        'schedule': crontab(minute=0, hour="10, 19"),
    },
    'reinquiry_payment_autodebet_mandiri': {
        'task': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_mandiri_scheduler',
        'schedule': crontab(minute=0, hour=10),
    },
    'gopay_autodebet_subscription_retry': {
        'task': 'juloserver.autodebet.tasks.gopay_autodebet_subscription_retry',
        'schedule': crontab(minute=0, hour=14),
    },
}
