from celery.schedules import crontab

MERCHANT_FINANCING_SCHEDULE = {
    'send_list_new_merchant_financing_axiata': {
        'task': 'juloserver.merchant_financing.web_app.tasks.send_list_new_merchant_financing_axiata',
        'schedule': crontab(minute=0, hour="*/1"),
    },
    'send_list_new_merchant_financing_axiata_csv_upload': {
        'task': 'juloserver.merchant_financing.web_app.tasks.send_list_new_merchant_financing_axiata_csv_upload',
        'schedule': crontab(minute=0, hour="*/1"),
    },
    'trigger_update_late_fee_amount_mf_axiata': {
        'task': 'juloserver.merchant_financing.web_app.tasks.trigger_update_late_fee_amount_mf_axiata',
        'schedule': crontab(minute=0, hour=1),
    },
    'update_late_fee_amount_mf_std_scheduler_task': {
        'task': 'juloserver.merchant_financing.tasks.update_late_fee_amount_mf_std_scheduler_task',
        'schedule': crontab(minute=30, hour=0),
    },
}
