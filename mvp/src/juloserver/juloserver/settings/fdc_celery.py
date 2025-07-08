from celery.schedules import crontab

FDC_CELERYBEAT_SCHEDULE = {
    # 'trigger_download_outdated_loans_from_fdc': {
    #     'task': 'trigger_download_outdated_loans_from_fdc',
    #     'schedule': crontab(minute=0, hour=9)
    # },
    'trigger_download_statistic_from_fdc': {
        'task': 'trigger_download_statistic_from_fdc',
        'schedule': crontab(minute=3, hour=15)
    },
    'trigger_download_result_fdc': {
        'task': 'trigger_download_result_fdc',
        'schedule': crontab(minute=0, hour=8)
    },
    'trigger_upload_loans_data_to_fdc': {
        'task': 'trigger_upload_loans_data_to_fdc',
        'schedule': crontab(minute=0, hour=2)
    },
    'trigger_alert_unexpected_fdc_status': {
        'task': 'alert_unexpected_status_fdc_api',
        'schedule': crontab(minute=1, hour='*/1')
    },
}
