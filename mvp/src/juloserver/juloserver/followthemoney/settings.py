from celery.schedules import crontab

FOLLOWTHEMONEY_SCHEDULE = {
    'partner_bulk_disbursement': {
        'task': 'juloserver.followthemoney.tasks.partner_bulk_disbursement',
        'schedule': crontab(minute=5, hour=0),
    },
    # 'exclude_write_off_loans_from_current_lender_balance': {
    #     'task': 'juloserver.followthemoney.tasks.exclude_write_off_loans_from_current_lender_balance',
    #     'schedule': crontab(minute=20, hour=1),
    # },
    # 'reconcile_lender_balance': {
    #     'task': 'juloserver.followthemoney.tasks.reconcile_lender_balance',
    #     'schedule': crontab(minute=5, hour=1),
    # },
    'scheduled_retry_for_reversal_payment_insufficient_balance': {
        'task': 'juloserver.followthemoney.tasks.scheduled_retry_for_reversal_payment_insufficient_balance',
        'schedule': crontab(minute=0, hour='*/4'),
    },
    'send_notification_current_balance_amount': {
        'task': 'juloserver.followthemoney.tasks.send_notification_current_balance_amount',
        'schedule': crontab(minute=0, hour=[8, 15, 18]),
    },
    'send_slack_notification_xendit_remaining_balance': {
        'task': 'juloserver.followthemoney.tasks.send_slack_notification_xendit_remaining_balance',
        'schedule': crontab(minute='*/10'),
    },
    'pusdafil_daily_process_lender_repayment_detail': {
        'task': 'juloserver.followthemoney.tasks.pusdafil_daily_process_lender_repayment_detail',
        'schedule': crontab(minute=0, hour=1),
    },
    'pusdafil_retry_process_lender_repayment_detail': {
        'task': 'juloserver.followthemoney.tasks.pusdafil_retry_process_lender_repayment_detail',
        'schedule': crontab(minute=0, hour=13),
    },
    'pusdafil_update_error_summary': {
        'task': 'juloserver.followthemoney.tasks.pusdafil_update_error_summary',
        'schedule': crontab(minute=0, hour=14),
    },
}
