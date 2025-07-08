from celery.schedules import crontab

FRAUD_SECURITY_SCHEDULE = {
    'juloserver.fraud_security.tasks.scan_fraud_hotspot_geohash_velocity_model': {
        'task': 'juloserver.fraud_security.tasks.scan_fraud_hotspot_geohash_velocity_model',
        'schedule': crontab(minute=0),  # Every Hour
    },
    'juloserver.fraud_security.tasks.swift_limit_drainer_account_daily_action': {
        'task': 'juloserver.fraud_security.tasks.swift_limit_drainer_account_daily_action',
        'schedule': crontab(hour=3, minute=0),
    },
    'juloserver.fraud_security.tasks.telco_maid_temporary_block_daily_action': {
        'task': 'juloserver.fraud_security.tasks.telco_maid_temporary_block_daily_action',
        'schedule': crontab(hour=3, minute=0),
    },
    'juloserver.fraud_security.tasks.save_bank_name_velocity_threshold_history': {
        'task': 'juloserver.fraud_security.tasks.save_bank_name_velocity_threshold_history',
        'schedule': crontab(hour=23, minute=30),
    },
    'juloserver.fraud_security.tasks.fraud_block_account_daily_action': {
        'task': 'juloserver.fraud_security.tasks.fraud_block_account_daily_action',
        'schedule': crontab(hour=3, minute=0),
    },
}
